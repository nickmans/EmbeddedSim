"""Persistent robot execution and deterministic reproduction of its input events."""
import argparse
from collections import deque
from contextlib import ExitStack
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from selectors import DefaultSelector, EVENT_READ
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Condition, Event, Thread
from time import monotonic
from uuid import uuid4

from config import SetupError, fault_channel, fault_evidence, fault_level, load_config, number, validate
from elf import validate_elf
from runner import ERRORS, WARNINGS, LOOP, PLATFORM, RENODE, decimal_args, machine_commands, read_elf, write_json

SLICE_NS = 100_000_000
DISPLAY_STRIDE = 20  # 1 ms recorded samples; retain 50 presentation samples per second.
MAX_DISPLAY_ROWS = 1501
MAX_LOG_BYTES = 4 * 1024 * 1024
TERMINAL = {"completed", "stopped", "failed"}
TRANSITIONS = {
    "start": {"ready"}, "pause": {"running"}, "resume": {"paused"},
    "stop": {"ready", "running", "paused"},
    "reset": {"ready", "running", "paused", *TERMINAL},
}


def config_hash(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def duration_ns(config):
    return int(round(Decimal(str(config["scenario"]["duration_s"])) * 1_000_000_000))


class Monitor:
    """Own the private monitor pipe. No command from HTTP is passed through verbatim."""
    def __init__(self, scratch, log_path, cancelled):
        self.cancelled = cancelled
        self.log = log_path.open("ab", buffering=0)
        try:
            self.process = subprocess.Popen(
                [str(RENODE), "--disable-gui", "--plain", "--console"],
                cwd=scratch, env=dict(os.environ, XDG_CONFIG_HOME=str(scratch / "config")),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except BaseException:
            self.log.close()
            raise
        self.selector = DefaultSelector()
        self.selector.register(self.process.stdout, EVENT_READ)
        self.buffer = b""
        self.warnings = set()

    def command(self, command, timeout=20):
        if self.cancelled.is_set():
            raise SetupError("Session closed.")
        token = uuid4().hex
        self.process.stdin.write(f'{command}\necho "{token}"\n'.encode("ascii"))
        self.process.stdin.flush()
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self.cancelled.is_set():
                raise SetupError("Session closed.")
            for key, _ in self.selector.select(0.2):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    raise SetupError("Renode exited during a live command. See renode.log.")
                if self.log.tell() < MAX_LOG_BYTES:
                    self.log.write(chunk)
                lines = (self.buffer + chunk).split(b"\n")
                self.buffer = lines.pop()
                if len(self.buffer) > 65536:
                    raise SetupError("Renode produced an oversized monitor line.")
                for line in lines:
                    text = line.decode("utf-8", errors="replace")
                    warning = WARNINGS.search(text)
                    if warning and len(self.warnings) < 12:
                        self.warnings.add(warning[1].strip()[:300])
                    if ERRORS.search(text):
                        raise SetupError(f"Renode command failed. {text.strip()}")
                    if text.strip() == token:
                        return
        raise SetupError("Renode live command timed out. See renode.log.")

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    self.process.stdin.write(b"quit\n")
                    self.process.stdin.flush()
                    self.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    if self.process.poll() is None:
                        try:
                            os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    self.process.wait()
        finally:
            self.selector.close()
            for stream in (self.process.stdin, self.process.stdout, self.log):
                try:
                    stream.close()
                except OSError:
                    pass


class LiveMachine:
    """One fresh machine and lossless recording, accessed by its owner only."""
    def __init__(self, image, config, output, cancelled):
        self.config = config
        self.elf_sha256 = hashlib.sha256(image).hexdigest()
        self.output = output
        self.cancelled = cancelled
        self.limit = duration_ns(config)
        self.virtual_ns = 0
        self.samples = 0
        self.active_seconds = 0
        self.display = deque(maxlen=MAX_DISPLAY_ROWS)
        self.latest = None
        self.header = ""
        self.events = []
        self.unapplied_faults = []
        self.fault_enabled = fault_evidence(config)
        self.finalized = False

        self.resources = ExitStack()
        try:
            output.mkdir(parents=True, exist_ok=False)
            write_json(output / "config.json", config)
            self.scratch = Path(self.resources.enter_context(TemporaryDirectory(prefix="embeddedsim-live-", dir="/tmp")))
            with (output / "renode.log").open("wb") as log:
                subprocess.run([sys.executable, str(PLATFORM / "prepare.py"), str(self.scratch)],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=30)
            script = self.scratch / "boot.resc"
            commands = machine_commands(self.scratch, validate_elf(image), config)
            script.write_text("\n".join(["logLevel 2", *commands]) + "\n")
            self.monitor = Monitor(self.scratch, output / "renode.log", cancelled)
            self.resources.callback(self.monitor.close)
            self.monitor.command(f"include @{script}", timeout=50)
            self.capture()
        except BaseException:
            self.close()
            raise

    def capture(self):
        path = self.scratch / "slice.csv"
        self.monitor.command(f'{LOOP} ExportLive "{path}" {self.samples}')
        with path.open() as stream:
            self.virtual_ns = int(stream.readline())
            header = stream.readline().rstrip("\n")
            if not self.header:
                self.header = header
                (self.output / "recording.part").write_text(self.header + "\n")
            with (self.output / "recording.part").open("a") as recording:
                for line in stream:
                    row = line.rstrip("\n")
                    self.samples += 1
                    self.latest = row
                    if self.samples == 1 or self.samples % DISPLAY_STRIDE == 0:
                        self.display.append(row)
                    recording.write(line)

    def step(self, end):
        target = min(self.virtual_ns + SLICE_NS, end)
        if target <= self.virtual_ns:
            raise SetupError("Expected a future live execution boundary.")
        started = monotonic()
        interval = Decimal(target - self.virtual_ns) / 1_000_000_000
        self.monitor.command(f'emulation RunFor "{interval:.9f}"')
        self.capture()
        self.active_seconds += monotonic() - started
        if self.virtual_ns != target:
            raise SetupError(f"Renode stopped at {self.virtual_ns} ns, expected {target} ns.")

    def apply(self, change):
        if "channel" in change:
            channel = fault_channel(change["channel"])
            level = change["level"]
            self.monitor.command(f"{LOOP} SetLiveEncoderFault {channel} {-1 if level is None else level}")
        else:
            self.monitor.command(decimal_args(f"{LOOP} SetLiveRightDrag", (change["right_Nms"],)))
        event = {"sequence": len(self.events) + 1, "at_ns": self.virtual_ns, **change}
        self.events.append(event)
        return event

    def write_events(self, state):
        temporary = self.output / "events.part"
        log = {"version": 2 if self.fault_enabled else 1, "elf_sha256": self.elf_sha256, "boundary_ns": SLICE_NS,
               "config_sha256": config_hash(self.config), "events": self.events,
               "end_virtual_ns": self.virtual_ns, "state": state}
        if self.fault_enabled:
            log["unapplied_faults"] = self.unapplied_faults
        write_json(temporary, log)
        temporary.replace(self.output / "events.json")

    def finish(self, state):
        self.write_events(state)
        if self.samples:
            (self.output / "recording.part").replace(self.output / "recording.csv")
        self.finalized = True

    def close(self):
        self.resources.close()


class LiveSession:
    """One worker serializes commands, slices, archives and fresh-machine resets."""
    def __init__(self, image, config, output_root):
        validate(config)
        validate_elf(image)
        self.id = uuid4().hex
        self.image, self.config, self.output_root = image, config, output_root
        self.condition, self.cancelled = Condition(), Event()
        self.pending = None
        self.queued_drag = None
        self.revision = 0
        self.info = {}
        self.display = ()
        self.header = self.latest = ""
        self.generation = 0
        self.new_generation()
        self.worker = Thread(target=self.work, daemon=True, name="embedded-robot-" + self.id[:8])
        self.worker.start()

    def new_generation(self):
        self.recording_id = uuid4().hex
        self.generation += 1
        self.state = "preparing"
        self.started = self.ended = None
        self.last_event = self.last_fault_event = None
        self.queued_fault = None
        self.live_faults = {}
        self.error = None
        self.queued_drag = None
        self.info = {}
        self.display = ()
        self.header = self.latest = ""
        self.revision += 1

    def status(self, since=None, cursor=None):
        with self.condition:
            wall = (self.ended or monotonic()) - self.started if self.started is not None else 0
            state = {"id": self.id, "generation": self.generation, "recording_id": self.recording_id,
                     "state": self.state, "control_pending": self.pending, "pending_right_Nms": self.queued_drag,
                     "fault_enabled": fault_evidence(self.config), "pending_fault": self.queued_fault,
                     "last_fault_event": self.last_fault_event, "live_faults": dict(self.live_faults),
                     "last_event": self.last_event, "error": self.error, "wall_seconds": wall,
                     "revision": self.revision, "virtual_ns": 0, "samples": 0, "speed": 0,
                     "duration_ns": duration_ns(self.config),
                     "initial_pose": self.config["scenario"]["initial_pose"],
                     "geometry": self.config["robot"]["body"], **self.info}
            if cursor is not None:
                generation, offset = cursor
                reset = generation != self.generation or offset > len(self.display)
                state["display"] = {"offset": 0 if reset else offset,
                                    "rows": self.display[0 if reset else offset:],
                                    "latest": self.latest}
                if reset or offset == 0:
                    state["display"]["header"] = self.header
            elif since != self.revision:
                state["csv"] = "\n".join((self.header, *self.display, self.latest, "") if self.latest
                                          else (self.header, *self.display, "")) if self.header else ""
            return state

    def active(self):
        with self.condition:
            return self.state not in TERMINAL or self.pending == "reset"

    def submit(self, action, value=None):
        with self.condition:
            if self.cancelled.is_set():
                raise SetupError("The live session has closed.")
            if action == "load":
                if self.state not in {"running", "paused"} or self.queued_drag is not None or self.pending in {"stop", "reset"}:
                    raise SetupError("Queue one load change while running or paused.")
                self.queued_drag = number(value, 0, 0.02, "Right viscous resistance (N·m/(rad/s))")
            elif action == "fault":
                if not fault_evidence(self.config):
                    raise SetupError("Enable encoder fault evidence in the scenario before preparing a live run.")
                if self.state not in {"running", "paused"} or self.queued_fault is not None or self.pending in {"stop", "reset"}:
                    raise SetupError("Queue one encoder fault change while running or paused.")
                fault_channel(value["channel"])
                fault_level(value["level"], allow_clear=True)
                self.queued_fault = value
            else:
                if self.pending or self.state not in TRANSITIONS.get(action, ()):
                    raise SetupError(f"Cannot {action} while {self.state} or another control is pending.")
                self.pending = action
            self.condition.notify_all()
            return self.status(since=self.revision)

    def publish(self, machine):
        self.display = tuple(machine.display)
        self.header = machine.header if self.display else ""
        self.latest = machine.latest if self.display and machine.latest != self.display[-1] else ""
        self.revision += 1
        self.info = {"virtual_ns": machine.virtual_ns, "samples": machine.samples,
                     "warnings": sorted(machine.monitor.warnings),
                     "speed": (machine.virtual_ns / 1e9 / machine.active_seconds) if machine.active_seconds else 0}

    def work(self):
        machine = None
        try:
            while not self.cancelled.is_set():
                try:
                    if self.state == "preparing":
                        machine = LiveMachine(self.image, self.config, self.output_root / self.recording_id, self.cancelled)
                        with self.condition:
                            self.state = "ready"
                            self.publish(machine)
                    with self.condition:
                        self.condition.wait_for(lambda: self.cancelled.is_set() or self.pending or self.state == "running")
                        if self.cancelled.is_set():
                            break
                        action = self.pending
                        if action == "start":
                            self.started = monotonic()
                            self.state = "running"
                        elif action == "pause":
                            self.state = "paused"
                        elif action == "resume":
                            self.state = "running"
                        if action not in {"stop", "reset"}:
                            self.pending = None
                        running = self.state == "running"
                        drag = self.queued_drag if running else None
                        fault = self.queued_fault if running else None
                    if action in {"stop", "reset"}:
                        if machine:
                            with self.condition:
                                self.archive_pending_fault(machine, action)
                                machine.finish("stopped")
                            machine.close()
                            machine = None
                        with self.condition:
                            self.pending = None
                            self.queued_drag = None
                            if action == "reset":
                                self.new_generation()
                            else:
                                self.ended = monotonic()
                                self.state = "stopped"
                        continue
                    if not running:
                        continue
                    if drag is not None:
                        event = machine.apply({"right_Nms": drag})
                        with self.condition:
                            self.queued_drag = None
                            self.last_event = event
                    if fault is not None:
                        event = machine.apply(fault)
                        with self.condition:
                            self.queued_fault = None
                            self.last_fault_event = event
                            if fault["level"] is None:
                                self.live_faults.pop(fault["channel"], None)
                            else:
                                self.live_faults[fault["channel"]] = fault["level"]
                    if drag is not None or fault is not None:
                        machine.write_events("running")
                    machine.step(machine.limit)
                    with self.condition:
                        self.publish(machine)
                    if machine.virtual_ns == machine.limit:
                        machine.close()
                        with self.condition:
                            self.archive_pending_fault(machine, "completed")
                            machine.finish("completed")
                            machine = None
                            self.state = "completed"
                            self.ended = monotonic()
                            self.queued_drag = None
                            if self.pending != "reset":
                                self.pending = None
                except Exception as error:
                    if self.cancelled.is_set():
                        break
                    if machine:
                        if machine.fault_enabled:
                            with self.condition:
                                self.archive_pending_fault(machine, "failed")
                                try:
                                    machine.finish("failed")
                                except OSError:
                                    pass
                        machine.close()
                        machine = None
                    with self.condition:
                        self.error = str(error)
                        self.state = "failed"
                        self.ended = monotonic()
                        self.pending = self.queued_drag = None
        finally:
            if machine:
                machine.close()
                if not machine.finalized:
                    with self.condition:
                        self.archive_pending_fault(machine, "shutdown")
                        machine.finish("stopped")

    def archive_pending_fault(self, machine, reason):
        if self.queued_fault is not None:
            machine.unapplied_faults.append({**self.queued_fault, "reason": reason})
            self.queued_fault = None

    def close(self):
        with self.condition:
            self.cancelled.set()
            self.condition.notify_all()
        self.worker.join()


def reproduce(image, config, schedule, output):
    validate(config)
    validate_elf(image)
    version = 2 if fault_evidence(config) else 1
    if not isinstance(schedule, dict) or schedule.get("version") != version or schedule.get("boundary_ns") != SLICE_NS:
        raise SetupError(f"Expected a version {version} live event log for this configuration.")
    if schedule.get("elf_sha256") != hashlib.sha256(image).hexdigest():
        raise SetupError("ELF SHA-256 differs from the recorded session.")
    if schedule.get("config_sha256") != config_hash(config):
        raise SetupError("Initial configuration differs from the recorded session.")
    end = schedule.get("end_virtual_ns")
    events = schedule.get("events")
    if type(end) != int or not 0 <= end <= duration_ns(config) or (end % SLICE_NS and end != duration_ns(config)):
        raise SetupError("Recorded end is outside the configured virtual-time boundaries.")
    if not isinstance(events, list) or len(events) > version * (end // SLICE_NS + 1):
        raise SetupError("Invalid event list.")
    previous = (-1, -1)
    for i, event in enumerate(events, 1):
        if not isinstance(event, dict) or event.get("sequence") != i:
            raise SetupError("Invalid event sequence.")
        at = event.get("at_ns")
        kind = int("channel" in event)
        if type(at) != int or not previous < (at, kind) or not 0 <= at <= end or at % SLICE_NS:
            raise SetupError("An event is not at an ordered execution boundary.")
        if version == 2 and kind:
            if set(event) != {"sequence", "at_ns", "channel", "level"}:
                raise SetupError("Invalid recorded fault change.")
            fault_channel(event["channel"])
            fault_level(event["level"], allow_clear=True)
        else:
            if set(event) != {"sequence", "at_ns", "right_Nms"}:
                raise SetupError("Invalid recorded load change.")
            number(event["right_Nms"], 0, 0.02, "Right viscous resistance")
        previous = (at, kind)
    terminal_state = "completed" if end == duration_ns(config) else "stopped"
    if version == 2:
        terminal_state = schedule.get("state", terminal_state)
        if not isinstance(terminal_state, str) or terminal_state not in TERMINAL or (terminal_state == "completed" and end != duration_ns(config)):
            raise SetupError("Invalid recorded terminal state.")
    unapplied = schedule.get("unapplied_faults", [])
    if not isinstance(unapplied, list) or len(unapplied) > 1 or (version == 1 and unapplied):
        raise SetupError("Invalid unapplied fault list.")
    for change in unapplied:
        if not isinstance(change, dict) or set(change) != {"channel", "level", "reason"} or change["reason"] not in (
                "stop", "reset", "completed", "failed", "shutdown"):
            raise SetupError("Invalid unapplied fault change.")
        fault_channel(change["channel"])
        fault_level(change["level"], allow_clear=True)

    machine = LiveMachine(image, config, output, Event())
    try:
        index = 0
        while True:
            while index < len(events) and events[index]["at_ns"] == machine.virtual_ns:
                change = {key: value for key, value in events[index].items() if key not in ("sequence", "at_ns")}
                machine.apply(change)
                index += 1
            if machine.virtual_ns == end:
                break
            machine.step(end)
        machine.unapplied_faults = unapplied
        machine.finish(terminal_state)
        return machine.samples
    finally:
        machine.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        samples = reproduce(read_elf(args.elf), load_config(args.config),
                            json.loads(args.events.read_text()), args.output)
        print(f"Reproduced {samples} samples in {args.output}")
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
