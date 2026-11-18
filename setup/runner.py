"""Run a validated configuration and a supplied firmware image on a fresh machine."""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from assertions import run_assertions
from config import (ENDPOINTS, PWM_SIGNAL_PROFILE, ROOT, SetupError, fault_channel, fault_evidence,
                    fault_time_ns, load_config, validate)
import pwm_signal
from discovery import decode_snapshots
from elf import MAX_ELF_BYTES, validate_elf

CACHE = Path(os.environ.get("EMBEDDEDSIM_CACHE", Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "embeddedsim"))
TOOLS = Path(os.environ.get("EMBEDDEDSIM_TOOLS_DIR", CACHE / "tools")).expanduser().resolve()
RENODE = Path(os.getenv("RENODE_ROOT", str(TOOLS / "renode_1.17.0-portable"))) / "renode"
GCC = os.getenv("ARM_GCC", str(TOOLS / "xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc"))
PLATFORM = ROOT / "emulation/renode"
LOOP = "sysbus.gpioPortA.robotBody"
PROBE = "sysbus.robotProbe"
PIN_ORDER = ("PA0", "PA1", "PA4", "PA5")
ERRORS = re.compile(r"\[ERROR\]|error CS\d+|Errors during compilation|There was an error|"
                    r"No such command|Unhandled exception|Unexpected exception", re.IGNORECASE)

WARNINGS = re.compile(r"\[WARNING\]\s*(.*)")

class DiscoveryTimeout(SetupError):
    """A bounded Renode discovery command exceeded its wall deadline."""


def read_elf(path):
    try:
        with Path(path).open("rb") as handle:
            return handle.read(MAX_ELF_BYTES + 1)
    except OSError as error:
        raise SetupError(f"Could not read ELF: {error}") from error


def build_example(output, source="firmware/robot/controller.c"):
    command = [GCC, "-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=soft", "-O1", "-g",
               "-ffreestanding", "-nostdlib", "-Wl,--build-id=none", "-T",
               str(ROOT / "firmware/motor/link.ld"), str(ROOT / source),
               "-lm", "-lc", "-lgcc", "-o", str(output)]
    try:
        subprocess.run(command, cwd=ROOT, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise SetupError(f"Example build failed. Run experiments/renode-smoke/bootstrap.sh first. {error}") from error


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def robot_platform(config, discovery):
    wiring = config["wiring"]
    has_devices = any(wiring.values())
    platform = (PLATFORM / "stm32f407vg-robot.repl").read_text()
    if has_devices:
        platform += f'''
robotBody: Miscellaneous.RobotLoop @ gpioPortA
    portA: gpioPortA
    portB: gpioPortB
    exampleObserver: {str(not discovery and config["scenario"]["observer"] == "example-v1").lower()}
'''
    if discovery:
        platform += "\nrobotProbe: Miscellaneous.RobotDiscovery @ sysbus\n"
    destinations = {pin: [] for pin in PIN_ORDER}
    for index, endpoint in enumerate(("left.pwm", "right.pwm", "left.direction", "right.direction")):
        if wiring[endpoint]:
            destinations[wiring[endpoint]].append(f"robotBody@{index}")
    if discovery:
        for index, pin in enumerate(PIN_ORDER):
            destinations[pin].append(f"robotProbe@{index}")
    if any(destinations.values()):
        platform += "\ngpioPortA:\n"
        for pin, targets in destinations.items():
            if targets:
                platform += f"    {pin[-1]} -> {' | '.join(targets)}\n"
    return platform


def decimal_args(command, values):
    return command + " " + " ".join(f'"{Decimal(str(value)):f}"' for value in values)


def configure_robot(config):
    body = config["robot"]["body"]
    scenario = config["scenario"]
    pose = scenario["initial_pose"]
    wiring = config["wiring"]
    routes = {None: -1, "PA6": 0, "PB6": 1}
    commands = [
        decimal_args(f"{LOOP} ConfigureBody", (body[k] for k in ("mass_kg", "yaw_inertia_kg_m2",
                     "wheel_radius_m", "track_width_m", "wheel_inertia_kg_m2"))),
        decimal_args(f"{LOOP} SetInitialPose", (pose[k] for k in ("x_m", "y_m", "heading_rad"))),
        f'{LOOP} SetEncoderRoutes {routes[wiring["left.encoder_a"]]} {routes[wiring["right.encoder_a"]]}',
    ]
    for event in scenario["loads"]:
        commands.append(decimal_args(f"{LOOP} AddLoad", (event[k] for k in ("start_s", "end_s", "left_Nms", "right_Nms"))))
    if fault_evidence(config):
        commands.append(f"{LOOP} EnableEncoderEvidence")
        for fault in scenario.get("encoder_faults", []):
            start, end = (fault_time_ns(fault[key], scenario["duration_s"]) for key in ("start_s", "end_s"))
            commands.append(f'{LOOP} AddEncoderFault {fault_channel(fault["channel"])} {fault["level"]} {start} {end}')
        commands.append(f"{LOOP} InitializeEncoderFaults")
    return commands


def verify_trace(path, duration):
    with path.open(newline="") as handle:
        rows = csv.DictReader(handle)
        count = 0
        previous = -1
        for row in rows:
            try:
                t = float(row["time_s"])
                if not all(math.isfinite(float(value)) for value in row.values()) or t <= previous:
                    raise ValueError
            except (TypeError, ValueError, KeyError) as error:
                raise SetupError("Renode produced malformed or nonfinite trace data.") from error
            previous = t
            count += 1
    if not count or abs(previous - duration) > 0.0011:
        raise SetupError(f"Recording ended at {previous:g} s before the requested {duration:g} s. Check firmware startup and Renode logs.")
    return count


def machine_commands(scratch, segments, config, discovery=False):
    signal_profile = config["target"]["profile"] == PWM_SIGNAL_PROFILE
    models = ["QualifiedSTM32Timer", "QualifiedSTM32RCC", "STM32AFInput"]
    platform = scratch / "platform.repl"
    if signal_profile:
        shutil.copyfile(PLATFORM / "stm32f407vg-pwm.repl", platform)
        shutil.copyfile(ROOT / "integration/renode/PwmBenchProbe.cs", scratch / "PwmBenchProbe.cs")
        models.append("PwmBenchProbe")
    else:
        for source in ("models/Motor.cs", "models/DifferentialDrive.cs",
                       "integration/renode/RobotLoop.cs", "integration/renode/RobotDiscovery.cs"):
            shutil.copyfile(ROOT / source, scratch / Path(source).name)
        models += ["Motor", "DifferentialDrive", "RobotLoop"]
        if discovery:
            models.append("RobotDiscovery")
        platform.write_text(robot_platform(config, discovery))
    commands = [f"include @{scratch / (name + '.cs')}" for name in models]
    commands += ['mach create "stm32f407"', f"machine LoadPlatformDescription @{platform}"]
    if not signal_profile and any(config["wiring"].values()):
        commands += configure_robot(config)
    # Load just the validated PT_LOAD bytes. Firmware's reset handler owns .data/.bss startup.
    for index, (address, data) in enumerate(segments):
        path = scratch / f"segment{index}.bin"
        path.write_bytes(data)
        commands.append(f"sysbus LoadBinary @{path} 0x{address:08x}")
    commands.append("cpu VectorTableOffset 0x08000000")
    return commands


def run_job(image, config, output, operation, discovery_seconds=0.5):
    discovery = operation == "discover"
    validate(config, discovery)
    segments = validate_elf(image)
    signal_profile = config["target"]["profile"] == PWM_SIGNAL_PROFILE
    if discovery and (not math.isfinite(discovery_seconds) or not 0.01 <= discovery_seconds <= 3):
        raise SetupError("Discovery virtual time must be between 0.01 and 3 seconds.")
    if not RENODE.is_file():
        raise SetupError("Renode is missing. Run bash experiments/renode-smoke/bootstrap.sh first.")
    output = Path(output)
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise SetupError(f"Choose a new output directory: {error}") from error
    write_json(output / "config.json", config)
    result = {"operation": operation, "elf_sha256": hashlib.sha256(image).hexdigest()}
    with TemporaryDirectory(prefix="embeddedsim-", dir="/tmp") as tmp:
        scratch = Path(tmp)
        prep = subprocess.run([sys.executable, str(PLATFORM / "prepare.py"), str(scratch)],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)
        if prep.returncode:
            (output / "renode.log").write_text(prep.stdout + prep.stderr)
            raise SetupError("Could not prepare the qualified peripheral models; see renode.log.")
        commands = machine_commands(scratch, segments, config, discovery)
        if discovery:
            commands.append('echo "EmbeddedSim discovery: platform ready"')
        if signal_profile:
            capture = scratch / "pins.csv"
            edge_file = scratch / "edges.csv"
            fields = ",".join(f"{address:x}" for address in pwm_signal.REGISTERS.values())
            for snapshot in range(5):
                if snapshot:
                    commands.append(f'emulation RunFor "{discovery_seconds / 4:.9f}"')
                commands.append(f'sysbus.probe Capture "{capture}" "pins" "{fields}"')
                commands.append(f'echo "EmbeddedSim discovery: snapshot {snapshot + 1}/5"')
            commands.append(f'sysbus.probe Save "{edge_file}"')
        elif discovery:
            capture = scratch / "pins.tsv"
            for snapshot in range(5):
                if snapshot:
                    commands.append(f'emulation RunFor "{discovery_seconds / 4:.9f}"')
                commands.append(f'{PROBE} Capture "{capture}"')
                commands.append(f'echo "EmbeddedSim discovery: snapshot {snapshot + 1}/5"')
        else:
            capture = scratch / "recording.csv"
            duration = config["scenario"]["duration_s"]
            commands += [f'emulation RunFor "{duration:.9f}"', f'{LOOP} Finish "{capture}"']
        script = scratch / "run.resc"
        prefix = ["logLevel 2"]
        if discovery:
            prefix.append('echo "EmbeddedSim discovery: loading models and platform"')
        script.write_text("\n".join([*prefix, *commands, "quit"]) + "\n")
        log = output / "renode.log"
        with log.open("w") as handle:
            try:
                proc = subprocess.run([str(RENODE), "--disable-gui", "--console", "--plain", str(script)],
                                      cwd=scratch, env=dict(os.environ, XDG_CONFIG_HOME=str(scratch / "config")),
                                      stdout=handle, stderr=subprocess.STDOUT, timeout=45 if discovery else 240)
            except subprocess.TimeoutExpired as error:
                if discovery:
                    for artifact in (capture, scratch / "edges.csv"):
                        if artifact.is_file():
                            shutil.copyfile(artifact, output / f"partial-{artifact.name}")
                    raise DiscoveryTimeout(f"Discovery exceeded its {error.timeout:.0f} s wall-clock limit. "
                                           f"Inspect progress markers in {log}.") from error
                raise SetupError(f"{operation.title()} exceeded the wall-clock limit. Inspect renode.log.") from error
            except OSError as error:
                raise SetupError(f"Could not start Renode: {error}") from error
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - 65536))
            tail = handle.read().decode(errors="replace")
        failure = next((line.strip() for line in tail.splitlines() if ERRORS.search(line)), "")
        if proc.returncode or failure or not capture.is_file():
            raise SetupError(f"Renode did not complete {operation}. {failure or 'Inspect renode.log.'}")
        warnings = sorted({match[1][:300] for match in WARNINGS.finditer(tail)})[:12]
        if warnings:
            result["warnings"] = warnings
        if discovery:
            if signal_profile:
                result["snapshots"] = pwm_signal.decode(capture, edge_file)
                result["edge_channels"] = list(pwm_signal.SIGNALS)
                shutil.copyfile(edge_file, output / "signal-edges.csv")
            else:
                result["snapshots"] = decode_snapshots(capture)
                result["expected_endpoints"] = dict(ENDPOINTS)
            if not result["snapshots"][-1]["clock_profile_matches"]:
                result["diagnostics"] = [
                    f"Observed clocks do not match {config['target']['profile']} at the final snapshot. "
                    "Check startup or select the profile that matches the firmware. "
                    "Use pwm-signal-pll168-v1 for the qualified TIM2 capture/TIM3 PWM firmware."
                ]
            if len(result["snapshots"]) != 5:
                raise SetupError("Discovery ended before all virtual-time snapshots were captured.")
            if signal_profile and result["snapshots"][-1]["clock_profile_matches"]:
                pins = result["snapshots"][-1]["pins"]
                missing = [pin for pin in pwm_signal.ROUTES if not pin.startswith("PE") and not pins[pin]["qualified"]]
                if missing:
                    result["diagnostics"] = [
                        f"Expected capture, PWM or GPIO routes were not configured in the final snapshot: {', '.join(missing)}."
                    ]
        else:
            result["samples"] = verify_trace(capture, duration)
            shutil.copyfile(capture, output / "recording.csv")
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    for name in ("discover", "run"):
        operation = operations.add_parser(name)
        operation.add_argument("--config", type=Path, required=True, help="Version 1 JSON with explicit MCU/profile")
        operation.add_argument("--elf", type=Path, required=True)
        operation.add_argument("--output", type=Path, required=True, help="New directory for logs and results")
        if name == "discover":
            operation.add_argument("--seconds", type=float, default=0.5)
        else:
            operation.add_argument("--assertions", type=Path, help="Evaluate a version 1 outcome suite after recording")
    operations.add_parser("build-example").add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "build-example":
            if args.output.exists():
                raise SetupError("Choose a new output file for the example ELF.")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            build_example(args.output.resolve())
        else:
            config = load_config(args.config, args.operation == "discover")
            result = run_job(read_elf(args.elf), config, args.output, args.operation, getattr(args, "seconds", 0.5))
            for diagnostic in result.get("diagnostics", ()):
                print(diagnostic, file=sys.stderr)
            print(f"{args.operation.title()} complete: {args.output / 'result.json'} ({result['elf_sha256'][:12]})")
            if args.operation == "run" and args.assertions:
                return run_assertions(args.output / "recording.csv", args.assertions, args.output)
    except (OSError, SetupError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    sys.exit(main())
