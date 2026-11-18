"""Measure equivalent headless, unattended live and browser-connected runs."""
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))
from config import default_config
import live
import server
from runner import build_example

TIMINGS = {}


def instrument(cls, method):
    original = getattr(cls, method)
    @functools.wraps(original)
    def measured(self, *args, **kwargs):
        start = monotonic()
        try:
            return original(self, *args, **kwargs)
        finally:
            name = method
            if method == "command":
                if "RunFor" in args[0]:
                    name = "advance_and_export_monitor" if "ExportLive" in args[0] else "advance_monitor"
                else:
                    name = "export_monitor" if "ExportLive" in args[0] else "other_monitor"
            TIMINGS[name] = TIMINGS.get(name, 0) + monotonic() - start
    setattr(cls, method, measured)


def wait(test, timeout=300):
    end = monotonic() + timeout
    while monotonic() < end:
        found = test()
        if found:
            return found
        sleep(.004)
    raise RuntimeError("Benchmark timed out waiting for a state.")


def config_for(duration):
    config = default_config()
    config["scenario"].update(observer="example-v1", duration_s=duration)
    return config


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(args):
    args.output.mkdir(parents=True)
    elf = args.elf
    started = monotonic()
    if elf is None:
        elf = args.output / "example.elf"
        build_example(elf)
    build_time = monotonic() - started
    image = elf.read_bytes()
    for cls, methods in ((live.LiveMachine, ("__init__", "step", "capture", "presentation", "finish", "close")),
                         (live.Monitor, ("command",))):
        for method in methods:
            if hasattr(cls, method):
                instrument(cls, method)

    server.OUTPUT = args.output / "jobs"
    if args.modes == ["headless"] and not args.latency:
        api = browser = thread = None
    else:
        api = server.Server(0, image)
        thread = Thread(target=api.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{api.server_port}"
        browser = None
        if "browser" in args.modes:
            browser = subprocess.Popen(["node", str(Path(__file__).with_name("browser.mjs"))],
                                       text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def post(path, body):
        request = Request(base + path, data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Origin": base})
        with urlopen(request, timeout=15) as result:
            return json.load(result)

    def state(expected, condition=None):
        def check():
            with api.live.condition:
                value = api.live.status(since=api.live.revision)
            if value["state"] == "failed":
                raise RuntimeError(value["error"])
            return value if value["state"] == expected and (condition is None or condition(value)) else None
        return wait(check)

    def chromium(message):
        browser.stdin.write(json.dumps(message) + "\n")
        browser.stdin.flush()
        response = browser.stdout.readline()
        if not response:
            raise RuntimeError("Chromium client exited.")
        return json.loads(response)

    try:
        with (args.output / "measurements.jsonl").open("w") as log:
            def report(value):
                line = json.dumps(value, sort_keys=True)
                print(line, flush=True)
                log.write(line + "\n")
                log.flush()

            report({"elf": digest(elf), "build_s": build_time if args.elf is None else None,
                    "boundary_ns": live.SLICE_NS, "physics_step_ns": 25000})
            for repeat in range(args.repeats):
                for duration in args.durations:
                    for mode in (args.modes if repeat % 2 == 0 else args.modes[::-1]):
                        config = config_for(duration)
                        TIMINGS.clear()
                        start = monotonic()
                        if mode == "headless":
                            folder = args.output / f"headless-{duration}-{repeat}"
                            live.reproduce(image, config, {"version": 1, "boundary_ns": live.SLICE_NS,
                                "elf_sha256": digest(elf), "config_sha256": live.config_hash(config), "events": [],
                                "end_virtual_ns": duration * 10**9}, folder)
                            browser_stats = {}
                            elapsed = monotonic() - start
                        else:
                            response = post("/api/jobs", {"operation": "live", "config": config, "firmware": "example"})
                            endpoint = f"/api/live/{response['id']}"
                            run = state("ready")
                            folder = server.OUTPUT / run["recording_id"]
                            if mode == "browser":
                                chromium({"url": base + f"/viewer/?live={response['id']}"})
                            start = monotonic()
                            post(endpoint, {"action": "start"})
                            state("completed")
                            elapsed = monotonic() - start
                            browser_stats = chromium({}) if mode == "browser" else {}
                        report({"mode": mode, "duration_s": duration, "repeat": repeat + 1,
                                "elapsed_s": elapsed, "virtual_per_advancing_wall": duration / TIMINGS["step"],
                                "explicit_pause_s": 0, "recording_sha256": digest(folder / "recording.csv"),
                                "events_sha256": digest(folder / "events.json"),
                                "timings_s": dict(TIMINGS), **browser_stats})
                        if mode == "browser":
                            # Unattended subsequent runs have no previous viewer polling.
                            browser.stdin.close()
                            browser.wait(timeout=15)
                            browser = subprocess.Popen(["node", str(Path(__file__).with_name("browser.mjs"))],
                                                       text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

            if args.latency:
                config = config_for(12)
                entry = post("/api/jobs", {"operation": "live", "config": config, "firmware": "example"})
                endpoint = f"/api/live/{entry['id']}"
                state("ready")
                for trial in range(3):
                    post(endpoint, {"action": "start"})
                    state("running", lambda value: value["virtual_ns"] >= 200_000_000)
                    for action, destination in (("pause", "paused"), ("load", "paused"),
                                                ("resume", "running"), ("stop", "stopped"), ("reset", "ready")):
                        start = monotonic()
                        result = post(endpoint, {"action": action, "right_Nms": .004})
                        accepted = monotonic() - start
                        if action == "load":
                            assert result["pending_right_Nms"] == .004
                            queued = start
                            report({"command": "load_queued", "trial": trial + 1,
                                    "accept_ms": accepted * 1000, "virtual_ns": result["virtual_ns"]})
                            continue
                        result = state(destination, (lambda value: value["last_event"] is not None) if action == "resume" else None)
                        latency = monotonic() - start
                        report({"command": action, "trial": trial + 1, "accept_ms": accepted * 1000,
                                "settled_ms": latency * 1000, "virtual_ns": result["virtual_ns"]})
                        if action == "resume":
                            report({"command": "load_applied", "trial": trial + 1,
                                    "since_resume_ms": latency * 1000, "since_queue_ms": (monotonic() - queued) * 1000,
                                    "virtual_ns": result["last_event"]["at_ns"]})
    finally:
        if browser:
            if not browser.stdin.closed:
                browser.stdin.close()
            browser.wait(timeout=15)
        if api:
            api.shutdown()
            thread.join()
            api.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--durations", nargs="+", type=int, default=[10, 30])
    parser.add_argument("--modes", nargs="+", choices=["headless", "live", "browser"], default=["headless", "live", "browser"])
    parser.add_argument("--latency", action="store_true")
    measure(parser.parse_args())
