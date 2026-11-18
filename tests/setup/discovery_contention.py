"""Measure discovery wall time, CPU time, and termination under controlled contention."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))
from runner import build_example


def measure(output, groups):
    output.mkdir(parents=True)
    elf = output / "example.elf"
    build_example(elf)
    cpu = min(os.sched_getaffinity(0))

    def case(name, constrained):
        folder = output / name
        args = [sys.executable, "setup/runner.py", "discover", "--elf", str(elf),
                "--config", "setup/default.json", "--output", str(folder)]
        if constrained:
            args = ["taskset", "-c", str(cpu), *args]
        start = monotonic()
        samples = {}
        with subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            while proc.poll() is None:
                # Some kernels omit task/children. Read process stat to identify the direct child.
                for stat in Path("/proc").glob("[0-9]*/stat"):
                    try:
                        name_and_pid, fields = stat.read_text().rsplit(") ", 1)
                        if not name_and_pid.endswith("(renode"):
                            continue
                        state = fields.split()
                        if int(state[1]) == proc.pid:
                            samples[stat.parent.name] = (int(state[11]) + int(state[12])) / os.sysconf("SC_CLK_TCK")
                    except (OSError, ValueError, IndexError):
                        continue
                sleep(.25)
            cli_output = proc.communicate()[0].strip()
        log = folder / "renode.log"
        stages = [line.strip() for line in log.read_text(errors="replace").splitlines()
                  if line.strip().startswith("EmbeddedSim discovery:")] if log.exists() else []
        return {"name": name, "wall_s": round(monotonic() - start, 2),
                "observed_renode_cpu_s": samples, "exit": proc.returncode, "last_stage": stages[-1] if stages else None,
                "leftover_pids": [pid for pid in samples if Path(f"/proc/{pid}").exists()], "output": cli_output}

    with (output / "measurements.jsonl").open("w") as stream:
        for group in groups:
            constrained = group.startswith("one-cpu")
            parallel = group.endswith("parallel")
            if parallel:
                with ThreadPoolExecutor(4) as executor:
                    results = list(executor.map(lambda i: case(f"{group}-{i}", constrained), range(4)))
            else:
                results = [case(group, constrained)]
            for result in results:
                line = json.dumps(result)
                print(line, flush=True)
                stream.write(line + "\n")
                stream.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    labels = ["normal-isolated", "one-cpu-isolated", "native-parallel", "one-cpu-parallel"]
    parser.add_argument("--groups", nargs="+", choices=labels, default=labels)
    args = parser.parse_args()
    measure(args.output.resolve(), args.groups)
