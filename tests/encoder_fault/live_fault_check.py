"""Verify encoder fault commands, saved logs, and lossless replay via the loopback API."""
import argparse
import json
from pathlib import Path
import sys
from threading import Thread
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "setup"), str(ROOT / "tests/setup")]

from assertions import read_recording
from config import SetupError, default_config, validate
from live import SLICE_NS, reproduce
from live_check import wait_for
from runner import build_example, run_job
import server


def scheduled_grid(image, output):
    config = default_config()
    config["scenario"].update(duration_s=3, observer="example-v1", loads=[], encoder_faults=[
        {"channel": "left.a", "level": 1, "start_s": 0, "end_s": .6},
        {"channel": "right.b", "level": 0, "start_s": 2.300025, "end_s": 2.5},
        {"channel": "right.b", "level": 1, "start_s": 2.5, "end_s": 2.9},
    ])
    validate(config)
    config["scenario"]["encoder_faults"][1]["start_s"] = 2.300001
    try:
        validate(config)
    except SetupError as error:
        assert "25 µs" in str(error)
    else:
        raise AssertionError("Accepted an off-grid fault time.")
    config["scenario"]["encoder_faults"][1]["start_s"] = 2.300025
    run_job(image, config, output, "run")
    data = read_recording(output / "recording.csv")
    for time, channel, wanted in ((.001, "left_a", 1), (.6, "left_a", -1),
                                  (2.3, "right_b", -1), (2.301, "right_b", 0),
                                  (2.5, "right_b", 1), (2.9, "right_b", -1)):
        index = data["time_s"].index(time)
        assert data[f"enc_{channel}_forced_level"][index] == wanted, (time, channel)
    print("PASS time-zero activation, 25 µs grid, and abutting low/high masks.")


def exercise(output):
    output.mkdir(parents=True)
    elf = output / "example.elf"
    build_example(elf)
    image = elf.read_bytes()
    server.OUTPUT = output / "jobs"
    config = default_config()
    config["scenario"].update(duration_s=8, loads=[], encoder_fault_evidence=True)
    with server.Server(0, image) as api:
        thread = Thread(target=api.serve_forever)
        thread.start()
        base = f"http://127.0.0.1:{api.server_port}"

        def request(path, payload=None, code=200):
            headers = {"Content-Type": "application/json", "Origin": base}
            data = None if payload is None else json.dumps(payload).encode()
            try:
                with urlopen(Request(base + path, data, headers), timeout=15) as result:
                    assert result.status == code
                    return json.load(result)
            except HTTPError as error:
                assert error.code == code, error.read()
                return json.load(error)

        try:
            session = request("/api/jobs", {"operation": "live", "config": config, "firmware": "example"}, 202)
            route = f"/api/live/{session['id']}"
            get = lambda: request(route)
            def command(action, code=202, **data):
                return request(route, {"action": action, **data}, code)
            def state(name):
                return wait_for(get, lambda value: value["state"] == name)
            def pause_at(time):
                wait_for(get, lambda value: value["virtual_ns"] >= time)
                command("pause")
                return state("paused")

            ready = state("ready")
            assert ready["fault_enabled"] and not ready["live_faults"]
            command("start")
            paused = pause_at(600_000_000)
            at = paused["virtual_ns"]
            assert at % SLICE_NS == 0
            fault = {"channel": "left.b", "level": 1}
            command("fault", 409, channel="left.b", level=True)
            command("fault", 409, channel="left.c", level=0)
            command("load", right_Nms=.001)
            assert command("fault", **fault)["pending_fault"] == fault
            command("fault", 409, channel="right.a", level=0)
            sleep(.25)
            stable = get()
            assert stable["virtual_ns"] == at and stable["last_fault_event"] is None
            command("resume")
            active = wait_for(get, lambda value: value["last_fault_event"] is not None)
            assert active["last_fault_event"] == {"sequence": 2, "at_ns": at, **fault}
            assert active["live_faults"] == {"left.b": 1}

            paused = pause_at(at + 400_000_000)
            clear = {"channel": "left.b", "level": None}
            clear_at = paused["virtual_ns"]
            assert command("fault", **clear)["pending_fault"] == clear
            command("resume")
            wait_for(get, lambda value: value["last_fault_event"]["level"] is None)
            pause_at(clear_at + 200_000_000)
            command("fault", **fault)
            command("reset")
            fresh = state("ready")
            assert fresh["generation"] == 2 and not fresh["live_faults"]
            assert fresh["pending_fault"] is None and fresh["last_fault_event"] is None
            command("stop")
            state("stopped")
        finally:
            api.shutdown()
            thread.join()

    original = server.OUTPUT / ready["recording_id"]
    schedule = json.loads((original / "events.json").read_text())
    assert schedule["version"] == 2
    assert schedule["unapplied_faults"] == [{**fault, "reason": "reset"}]
    assert schedule["events"] == [
        {"sequence": 1, "at_ns": at, "right_Nms": .001},
        {"sequence": 2, "at_ns": at, **fault},
        {"sequence": 3, "at_ns": clear_at, **clear},
    ]
    data = read_recording(original / "recording.csv")
    stop = data["time_s"].index(clear_at / 1e9)
    start = data["time_s"].index(at / 1e9) + 1
    assert set(data["enc_left_b_forced_level"][start:stop+1]) == {1}
    assert set(data["enc_left_b_delivered_level"][start:stop+1]) == {1}
    assert len(set(data["enc_left_b_delivered_edges"][start:stop+1])) == 1
    assert data["enc_left_b_physical_edges"][stop] > data["enc_left_b_physical_edges"][start]
    assert data["enc_left_b_delivered_edges"][-1] > data["enc_left_b_delivered_edges"][stop]
    assert data["enc_left_b_forced_level"][-1] == -1
    reproduce(image, config, schedule, output / "reproduced")
    for name in ("recording.csv", "events.json"):
        assert (original / name).read_bytes() == (output / "reproduced" / name).read_bytes(), name
    print("PASS live activation, clearing, pause/resume, load order, reset audit and byte-identical reproduction.")
    scheduled_grid(image, output / "grid")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    exercise(parser.parse_args().output.resolve())
