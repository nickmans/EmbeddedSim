"""Exercise the loopback live API, process lifetime and a replayed load event."""
import argparse
import base64
import csv
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))

from config import default_config
from live import SLICE_NS, reproduce
from runner import build_example
import server


def wait_for(get, condition, timeout=65):
    until = monotonic() + timeout
    while monotonic() < until:
        status = get()
        assert status["state"] != "failed", status["error"]
        if condition(status):
            return status
        sleep(.025)
    raise AssertionError(f"Live session did not reach the expected boundary: {status['state']}")


def processes():
    listing = subprocess.check_output(["ps", "-eo", "pid=,ppid=,comm="], text=True)
    return {int(pid) for line in listing.splitlines() for pid, parent, command in [line.split()]
            if int(parent) == os.getpid() and command == "renode"}


def trace(path):
    with path.open() as stream:
        return [{key: float(value) for key, value in row.items()} for row in csv.DictReader(stream)]


def exercise(output):
    output.mkdir(parents=True)
    elf = output / "example.elf"
    external = output / "external.elf"
    build_example(elf)
    build_example(external, "tests/setup/minimal.c")
    server.OUTPUT = output / "jobs"
    with server.Server(0, elf.read_bytes()) as api:
        thread = Thread(target=api.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{api.server_port}"

        def request(path, data=None, wanted=200):
            req = Request(base + path, headers={"Content-Type": "application/json", "Origin": base},
                          data=None if data is None else json.dumps(data).encode())
            try:
                with urlopen(req, timeout=5) as result:
                    assert result.status == wanted
                    return json.load(result)
            except HTTPError as error:
                assert error.code == wanted, (error.code, error.read())
                return json.load(error)

        def prepare(config, firmware="example"):
            return request("/api/jobs", {"operation": "live", "config": config, "firmware": firmware}, 202)

        try:
            config = default_config()
            config["scenario"].update(observer="example-v1", duration_s=4, loads=[])
            session = prepare(config)
            url = f"/api/live/{session['id']}"
            get = lambda: request(url)
            control = lambda action, **fields: request(url, {"action": action, **fields}, 202)
            ready = wait_for(get, lambda value: value["state"] == "ready")
            before = processes()
            assert len(before) == 1 and ready["virtual_ns"] == 0
            request("/api/jobs", {"operation": "run", "config": config, "firmware": "example"}, 409)

            ready_display = request(f"{url}?cursor=0:0")["display"]
            assert ready_display == {"offset": 0, "rows": [], "latest": "", "header": ""}
            control("start")
            running = wait_for(get, lambda value: value["virtual_ns"] >= 1_000_000_000)
            assert running["state"] == "running"
            assert float(list(csv.DictReader(running["csv"].splitlines()))[-1]["x_m"]) > .05
            snapshot = request(f"{url}?cursor=0:0")
            display = snapshot["display"]
            assert display["header"].startswith("time_s,") and display["rows"]
            offset = len(display["rows"])
            control("pause")
            paused = wait_for(get, lambda value: value["state"] == "paused")
            queued = control("load", right_Nms=.012)
            assert queued["last_event"] is None and queued["pending_right_Nms"] == .012
            sleep(.55)
            stable = get()
            for key in ("virtual_ns", "samples", "csv", "revision"):
                assert stable[key] == paused[key], key
            assert "csv" not in request(f"{url}?since={stable['revision']}")

            delta = request(f"{url}?cursor={snapshot['generation']}:{offset}")["display"]
            assert "header" not in delta and delta["offset"] == offset
            recovered = "\n".join([display["header"], *display["rows"], *delta["rows"],
                                    *([delta["latest"]] if delta["latest"] else []), ""])
            assert recovered == stable["csv"]
            control("resume")
            # Deliberately leave the API unread for multiple presentation intervals.
            sleep(.7)
            active = wait_for(get, lambda value: value["last_event"] is not None and value["virtual_ns"] > paused["virtual_ns"])
            assert processes() == before
            event = {"sequence": 1, "at_ns": paused["virtual_ns"], "right_Nms": .012}
            assert active["last_event"] == event and event["at_ns"] % SLICE_NS == 0
            wait_for(get, lambda value: value["virtual_ns"] >= event["at_ns"] + 1_000_000_000)
            control("stop")
            stopped = wait_for(get, lambda value: value["state"] == "stopped")
            assert not processes()

            for _ in range(2):
                previous = get()["recording_id"]
                control("reset")
                fresh = wait_for(get, lambda value: value["state"] == "ready" and value["recording_id"] != previous)
                assert len(processes()) == 1 and processes().isdisjoint(before)
                assert fresh["virtual_ns"] == 0 and fresh["last_event"] is None
                replaced = request(f"{url}?cursor={snapshot['generation']}:{offset}")["display"]
                assert replaced == ready_display
                before = processes()
            control("stop")
            wait_for(get, lambda value: value["state"] == "stopped")
            assert not processes()

            config["scenario"].update(observer="none", duration_s=.25)
            firmware = base64.b64encode(external.read_bytes()).decode()
            external_live = prepare(config, firmware)
            external_url = f"/api/live/{external_live['id']}"
            wait_for(lambda: request(external_url), lambda value: value["state"] == "ready")
            request(external_url, {"action": "start"}, 202)
            complete = wait_for(lambda: request(external_url), lambda value: value["state"] == "completed")
            external_path = server.OUTPUT / complete["recording_id"] / "recording.csv"
            assert "odom_x_m" not in trace(external_path)[0]
            assert trace(external_path)[-1]["wr_rad_s"] > 0 and not processes()

            passive = {"version": 1, "target": {"part": "stm32f407vgt6", "profile": "pwm-signal-pll168-v1"}}
            refusal = request("/api/jobs", {"operation": "live", "config": passive, "firmware": "example"}, 400)
            assert "discovery only" in refusal["error"]
        finally:
            api.shutdown()
            thread.join()

    original = server.OUTPUT / stopped["recording_id"]
    schedule = json.loads((original / "events.json").read_text())
    initial_config = json.loads((original / "config.json").read_text())
    assert schedule["events"] == [event] and schedule["end_virtual_ns"] == stopped["virtual_ns"]
    reproduce(elf.read_bytes(), initial_config, schedule, output / "reproduced")
    recorded = original / "recording.csv"
    assert recorded.read_bytes() == (output / "reproduced/recording.csv").read_bytes()

    reproduce(elf.read_bytes(), initial_config, {**schedule, "events": []}, output / "unloaded")
    loaded, unloaded = trace(recorded), trace(output / "unloaded/recording.csv")
    event_s = event["at_ns"] / 1e9
    assert all(a == b for a, b in zip(loaded, unloaded) if a["time_s"] <= event_s)
    assert next(row["time_s"] for row in loaded if row["right_drag_Nms"] > 0) == (event["at_ns"] + 1_000_000) / 1e9

    def change(key, start, end):
        return statistics.mean(a[key] - b[key] for a, b in zip(loaded, unloaded)
                               if event_s + start <= a["time_s"] < event_s + end)

    summary = {"event": event, "stopped_virtual_ns": stopped["virtual_ns"],
               "wall_seconds": stopped["wall_seconds"], "active_speed": stopped["speed"],
               "samples": len(loaded), "reproduction_byte_identical": True,
               "right_speed_delta_rad_s": change("wr_rad_s", .06, .2),
               "right_current_delta_A": change("ir_A", .25, .55),
               "right_pwm_duty_delta": change("duty_r", .25, .55)}
    assert summary["right_speed_delta_rad_s"] < -.1
    assert summary["right_current_delta_A"] > .1 and summary["right_pwm_duty_delta"] > .01
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"PASS live API, resets, pause/load/resume, and byte-identical reproduction. {output / 'summary.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    exercise(parser.parse_args().output.resolve())
