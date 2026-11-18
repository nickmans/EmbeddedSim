"""Run the pinned, unmodified third-party STM32 ELF on a bounded signal bench."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "setup"))

from elf import validate_elf
from pwm_signal import PWM_PINS, REGISTERS, SIGNALS, clock_tree
from runner import ERRORS, GCC, RENODE, read_elf

SHA256 = "25c2ab9e6d21a4743d311e00e1adae5e45247c3a9a14d82579e27b95bb7f3353"
PHASES = {"split": (700, 1400), "neutral": (1020, 1020), "swapped": (1400, 700)}
INPUT_PERIOD_US = 2041
RAM_SYMBOLS = (
    "SystemCoreClock", "uwTick", "Ton_PA0", "Ton_PA2", "DutyCycle_PA0", "DutyCycle_PA2",
    "IC_RisingEdge_PA0", "IC_FallingEdge_PA0", "IC_RisingEdge_PA2", "IC_FallingEdge_PA2",
)


def arm_tool(name):
    return str(Path(GCC).with_name("arm-none-eabi-" + name))


def symbol_addresses(elf):
    text = subprocess.check_output([arm_tool("nm"), "-n", str(elf)], text=True)
    symbols = dict(REGISTERS)
    for line in text.splitlines():
        items = line.split()
        if len(items) == 3 and items[-1] in RAM_SYMBOLS:
            symbols[items[-1]] = int(items[0], 16)
    assert all(name in symbols for name in RAM_SYMBOLS)
    assert all(0x20000000 <= symbols[name] < 0x20020000 for name in RAM_SYMBOLS)
    return symbols


def run_bench(segments, addresses, output, use_alias, legacy_clock):
    output.mkdir(parents=True, exist_ok=False)
    with TemporaryDirectory(prefix="third-party-pwm-", dir="/tmp") as tmp:
        work = Path(tmp)
        with (output / "renode.log").open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "emulation/renode/prepare.py"), str(work)],
                           stdout=log, stderr=subprocess.STDOUT, timeout=30, check=True)
        shutil.copyfile(ROOT / "integration/renode/PwmBenchProbe.cs", work / "PwmBenchProbe.cs")
        platform = (ROOT / "emulation/renode/stm32f407vg-pwm.repl").read_text()
        # Same bench for the negative control, with just the two alias lines omitted.
        if not use_alias:
            platform = platform.split("bitbandPeripherals:", 1)[0]
        if legacy_clock:
            platform = platform.replace(
                "systickClock: Miscellaneous.STM32F407SysTickClock @ sysbus\n    nvic: nvic\n", ""
            ).replace("    systickClock: systickClock\n", "")
        (work / "bench.repl").write_text(platform)
        commands = ["logLevel 2", *(f"include @{work / name}" for name in
                    ("QualifiedSTM32Timer.cs", "QualifiedSTM32RCC.cs", "STM32AFInput.cs", "PwmBenchProbe.cs")),
                    "mach create", f"machine LoadPlatformDescription @{work / 'bench.repl'}"]
        for i, (address, contents) in enumerate(segments):
            staged = work / f"segment{i}.bin"
            staged.write_bytes(contents)
            commands.append(f"sysbus LoadBinary @{staged} 0x{address:x}")
        commands.append("cpu VectorTableOffset 0x08000000")
        fields = ",".join(f"{address:x}" for address in addresses.values())

        def snapshot(name):
            commands.extend(["cpu PC", f'sysbus.probe Capture "{work / "registers.csv"}" "{name}" "{fields}"'])

        snapshot("reset")
        commands.extend(["sysbus.gpioPortA OnGPIO 0 false", "sysbus.gpioPortA OnGPIO 2 false"])
        time_us = 0
        planned = []
        def advance(instant):
            nonlocal time_us
            if instant > time_us:
                commands.append(f'emulation RunFor "{(instant - time_us)/1e6:.6f}"')
                time_us = instant

        if use_alias:
            for instant in (*range(1, 41), 50, 100, 250, 1000, 2000):
                advance(instant)
                snapshot(f"startup_{instant}us")
        advance(20000)
        snapshot("boot")
        for name, widths in (PHASES.items() if use_alias else ()):
            start = time_us
            events = []
            for pulse in range(8):
                rise = start + pulse * INPUT_PERIOD_US
                for pin, width in zip((0, 2), widths):
                    events.extend([(rise, pin, True), (rise + width, pin, False)])
            for instant, pin, level in sorted(events):
                if name == "split" and time_us == start and instant > start:
                    advance(start + 100)
                    snapshot("first_rising_serviced")
                advance(instant)
                commands.append(f"sysbus.gpioPortA OnGPIO {pin} {str(level).lower()}")
                planned.append((instant * 1000, f"PA{pin}", int(level)))
            end = start + 8 * INPUT_PERIOD_US
            advance(end)
            snapshot(name)
        commands.extend([f'sysbus.probe Save "{work / "edges.csv"}"', "quit"])
        (work / "play.resc").write_text("\n".join(commands) + "\n")
        with (output / "renode.log").open("a") as log:
            subprocess.run([str(RENODE), "--disable-gui", "--plain", "--console", str(work / "play.resc")],
                           env=dict(os.environ, XDG_CONFIG_HOME=str(work / "config")), cwd=work,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=45)
        log = (output / "renode.log").read_text()
        assert not ERRORS.search(log), f"Renode error: inspect {output / 'renode.log'}"
        pcs = [int(x, 16) for x in re.findall(r"(?m)^0x([0-9A-Fa-f]+)\s*$", log)]
        snapshots = {}
        with (work / "registers.csv").open() as stream:
            for index, (name, timestamp, *raw) in enumerate(csv.reader(stream)):
                snapshots[name] = {"virtual_ns": int(timestamp), "PC": pcs[index],
                                   **dict(zip(addresses, (int(x, 16) for x in raw), strict=True))}
        actual_inputs = []
        with (output / "output-edges.csv").open("w") as result, (work / "edges.csv").open() as source:
            writer = csv.writer(result)
            reader = csv.reader(source)
            writer.writerow(next(reader))
            for timestamp, signal, level in reader:
                name = SIGNALS[int(signal)]
                if name in ("PA0", "PA2"):
                    actual_inputs.append((int(timestamp), name, int(level)))
                else:
                    writer.writerow((timestamp, name, level))
        assert actual_inputs == planned, "Pin input timings differ from the planned stimulus"
        with (output / "input-edges.csv").open("w") as stream:
            writer = csv.writer(stream)
            writer.writerow(("virtual_ns", "signal", "level"))
            writer.writerows(actual_inputs)
    (output / "snapshots.json").write_text(json.dumps(snapshots, indent=2) + "\n")
    return snapshots, log


def require_route(snapshot, port, pin, mode, af=None):
    assert snapshot[f"{port}_MODER"] >> (pin * 2) & 3 == mode, (port, pin)
    if af is not None:
        assert snapshot[f"{port}_AFRL"] >> (pin * 4) & 15 == af, (port, pin)


def pin_level(edges, pin, before):
    return next((level for time, signal, level in reversed(edges) if signal == pin and time < before), 0)


def pin_activity(edges, pin, start, end, expected_period):
    window = [(t, level) for t, signal, level in edges if signal == pin and start <= t < end]
    rises = [t for t, level in window if level]
    highs = [b[0] - a[0] for a, b in zip(window, window[1:]) if a[1] and not b[1]]
    if not rises:
        assert not window and pin_level(edges, pin, end) == 0
        return {"period_ns": None, "duty": 0}
    periods = [b - a for a, b in zip(rises, rises[1:])]
    assert len(periods) > 5 and max(abs(p - expected_period) for p in periods) < 4, (pin, periods)
    return {"period_ns": statistics.mean(periods), "duty": statistics.mean(highs) / expected_period}


def qualify(snapshots, output):
    boot = snapshots["boot"]
    assert snapshots["reset"]["PA_MODER"] & 0xf != boot["PA_MODER"] & 0xf
    assert boot["virtual_ns"] == 20_000_000
    assert boot["SystemCoreClock"] == 168_000_000
    assert boot["RCC_CR"] & 0x03000000 == 0x03000000 and boot["RCC_CFGR"] & 0xFCFF == 0x940A
    assert boot["RCC_PLLCFGR"] & 0x0F437FFF == 0x04002A08
    assert boot["TIM2_CR1"] & 1 and boot["TIM2_DIER"] & 0x1F == 0xA
    assert boot["NVIC_ISER0"] & (1 << 28)
    assert boot["TIM2_CCMR1"] & 0xFF == boot["TIM2_CCMR2"] & 0xFF == 1
    assert boot["TIM2_CCER"] & 0x1111 == 0x101
    assert (boot["TIM2_PSC"], boot["TIM2_ARR"]) == (83, 2040)
    assert boot["TIM3_CR1"] & 1 and boot["TIM3_CCER"] & 0xFFFF == 0x1111
    assert boot["TIM3_CCMR1"] == boot["TIM3_CCMR2"] == 0x6868
    assert (boot["TIM3_PSC"], boot["TIM3_ARR"]) == (3, 8561)
    assert not boot["TIM4_CR1"] & 1 and not boot["TIM9_CR1"] & 1 and not boot["TIM9_CCER"] & 0x11
    for port, pins, mode, af in (("PA", (0, 2), 2, 1), ("PA", (6, 7), 2, 2),
                                 ("PB", (0, 1), 2, 2), ("PC", (0, 1, 2, 3), 1, None),
                                 ("PB", (3, 5), 1, None), ("PE", (5, 6), 2, 3)):
        for pin in pins:
            require_route(boot, port, pin, mode, af)
    assert boot["PA_PUPDR"] >> 4 & 3 == 1
    for port, mask in (("PA", 0xc0), ("PB", 0x2b), ("PC", 0x0f)):
        assert not boot[f"{port}_OTYPER"] & mask
    assert all(boot[name] == 0 for name in ("Ton_PA0", "Ton_PA2", "DutyCycle_PA0", "DutyCycle_PA2"))
    # Check that the ISR changed both channels to falling before either input fell.
    first_rise = snapshots["first_rising_serviced"]
    assert first_rise["virtual_ns"] == 20_100_000
    assert first_rise["TIM2_CCER"] & 0x3333 == 0x303

    with (output / "output-edges.csv").open() as stream:
        edges = [(int(t), signal, int(level)) for t, signal, level in list(csv.reader(stream))[1:]]
    expected_period = (boot["TIM3_PSC"] + 1) * (boot["TIM3_ARR"] + 1) * 1e9 / clock_tree(boot)["apb1_timer_hz"]
    previous = boot["virtual_ns"]
    assert boot["PC_ODR"] & 15 == 0 and boot["PB_ODR"] & 0x28 == 8
    assert all(boot[f"TIM3_CCR{i}"] == 8561 for i in range(1, 5))
    pre_input = {pin: pin_activity(edges, pin, previous - 4_000_000, previous, expected_period)
                 for pin in PWM_PINS}
    assert all(sample["duty"] > .999 for sample in pre_input.values())
    observations = {}
    for phase, widths in PHASES.items():
        state = snapshots[phase]
        end = state["virtual_ns"]
        assert end - previous == 8 * INPUT_PERIOD_US * 1000
        irq_rises = sum(previous <= t < end and signal == "TIM2_IRQn" and level
                        for t, signal, level in edges)
        assert irq_rises == (16 if phase == "neutral" else 24)
        assert state["TIM2_CCER"] & 0x3333 == 0x101
        duties = {}
        expected_compare = {}
        for pin, width in zip(("PA0", "PA2"), widths):
            ton = state[f"Ton_{pin}"]
            rise, fall = state[f"IC_RisingEdge_{pin}"], state[f"IC_FallingEdge_{pin}"]
            assert abs(ton - width) <= 2 and (fall - rise) % 2041 in range(width - 1, width + 2)
            assert ton == (fall - rise if fall > rise else 2040 - rise + fall)
            raw = struct.unpack("<f", struct.pack("<I", state[f"DutyCycle_{pin}"]))[0]
            assert abs(raw - 100 * ton / 2040) < 1e-5
            duties[pin] = raw
            if raw < 49:
                expected_compare[pin] = int((49 - (30 - (50 - raw) * .6)) / 49 * 8561)
            elif raw > 51:
                expected_compare[pin] = int(((70 + (raw - 50) * .6) - 51) / 49 * 8561)
            else:
                expected_compare[pin] = 0
        response = {}
        for i, pin in enumerate(PWM_PINS, start=1):
            source = "PA2" if i <= 2 else "PA0"
            ccr = state[f"TIM3_CCR{i}"]
            assert abs(ccr - expected_compare[source]) <= 1
            activity = pin_activity(edges, pin, end - 4_000_000, end, expected_period)
            assert abs(activity["duty"] - ccr / 8562) < .001
            response[pin] = {"ccr": ccr, **activity}
        brake = state["PB_ODR"] & 0x28
        direction = state["PC_ODR"] & 15
        assert brake == (32 if phase == "neutral" else 8)
        assert direction == (12 if phase == "swapped" else 3)
        assert all(pin_level(edges, f"PC{i}", end) == direction >> i & 1 for i in range(4))
        assert all(pin_level(edges, f"PB{i}", end) == brake >> i & 1 for i in (3, 5))
        observations[phase] = {"input_high_us": dict(zip(("PA0", "PA2"), widths)),
                               "firmware_capture_us": {pin: state[f"Ton_{pin}"] for pin in duties},
                               "firmware_duty_percent": duties, "irq_assertions": irq_rises,
                               "output_pwm": response, "PC0_through_PC3_mask": direction, "PB3_PB5_mask": brake}
        previous = end
    return observations, pre_input, expected_period


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-clock", action="store_true",
                        help="Measure stock fixed-clock SysTick while retaining the bit-band mapping")
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    args = parser.parse_args()
    image = read_elf(args.elf)
    assert hashlib.sha256(image).hexdigest() == SHA256, "Expected original pinned ELF bytes"
    segments = validate_elf(image)
    addresses = symbol_addresses(args.elf)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "elf.txt").open("w") as stream:
        subprocess.run([arm_tool("readelf"), "-hlA", "-p", ".comment", str(args.elf)],
                       stdout=stream, check=True)
    negative, negative_log = run_bench(segments, addresses, args.output / "without-bitband", False, args.legacy_clock)
    assert "0x42470060, value 0x1" in negative_log
    assert not negative["boot"]["RCC_CR"] & (1 << 25)
    assert negative["boot"]["SystemCoreClock"] == 16_000_000 and negative["boot"]["TIM2_CR1"] & 1 == 0
    source_lines = subprocess.check_output([arm_tool("addr2line"), "-f", "-e", str(args.elf),
                                            hex(negative["boot"]["PC"]), "0x08002ba0"], text=True)
    (args.output / "without-bitband" / "symbols.txt").write_text(source_lines)
    assert source_lines.startswith("Error_Handler\n") and "HAL_RCC_OscConfig" in source_lines
    fixed, fixed_log = run_bench(segments, addresses, args.output / "with-bitband", True, args.legacy_clock)
    assert "0x42470060" not in fixed_log
    phases, pre_input, period = qualify(fixed, args.output / "with-bitband")
    start_tick, final_tick = (fixed[key]["uwTick"] for key in ("boot", "swapped"))
    assert abs(final_tick - start_tick - (5 if args.legacy_clock else 49)) <= 1
    pre_pll = [state for label, state in fixed.items()
               if label.startswith("startup_") and state["RCC_CFGR"] & 0x0c == 0 and state["SYST_RVR"] == 15999]
    assert pre_pll, "The initial HSI SysTick reload was not observed"
    result = {
        "sha256": SHA256, "observer": "none", "legacy_clock": args.legacy_clock,
        "initial_systick_at_hsi": [
            {key: state[key] for key in ("virtual_ns", "SYST_RVR", "uwTick")}
            for state in pre_pll
        ],
        "without_peripheral_bitband": {
            "pc": f"0x{negative['boot']['PC']:08x}", "symbol": "Error_Handler",
            "clock_hz": negative["boot"]["SystemCoreClock"], "pll_ready": False,
        },
        "clock_hz": fixed["boot"]["SystemCoreClock"],
        "pin_configuration": {
            "PA0": "AF1 TIM2_CH1 direct input capture", "PA2": "AF1 TIM2_CH3 direct input capture",
            **{pin: f"AF2 TIM3_CH{i} PWM1" for i, pin in enumerate(PWM_PINS, start=1)},
            **{f"PC{i}": "GPIO push-pull direction" for i in range(4)},
            "PB3": "GPIO push-pull brake leg", "PB5": "GPIO push-pull brake leg",
            "PE5": "AF3 TIM9_CH1 configured, stopped", "PE6": "AF3 TIM9_CH2 configured, stopped",
        },
        "systick_after_pll": {
            "reload": fixed["boot"]["SYST_RVR"],
            "hal_tick_at_20_ms": fixed["boot"]["uwTick"],
            "hal_tick_at_end": fixed["swapped"]["uwTick"],
            "end_virtual_ns": fixed["swapped"]["virtual_ns"],
        },
        "pre_input_reverse": pre_input, "configured_pwm_period_ns": period,
        "phases": phases,
    }
    (args.output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS pinned third-party PWM bench. Evidence in {args.output}")


if __name__ == "__main__":
    main()
