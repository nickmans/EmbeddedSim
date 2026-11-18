# Discovery timeout investigation

The initial failed setup run timed out on the first attached example
discovery at the existing 45 s wall-clock limit. Other code paths in the
suite continued, and the discovery test passed when rerun with fewer
overlapping checks. The original unittest traceback survives in the
evidence archive. Its temporary test directory was removed at cleanup,
so the initial Renode log, probe progress, CPU-time sample, and scratch
files are unavailable. This prevents assigning a definitive cause to
that historical instance.

## Controlled reproduction

The test used the same example ELF, configuration, attached wiring,
Renode build, and 0.5 s virtual discovery in each case. The host was
Debian 13 x86‑64 with five available logical CPUs and a cgroup quota of
four CPU-seconds per wall second. The stress cases constrained CPU
affinity externally with `taskset`; no simulator timing or timeout
settings were altered. CPU seconds are the last observed process CPU
sample, not a sum of the parallel jobs. Wall time includes CLI setup.

| Case | Passes | Wall time | Observed Renode CPU time |
| --- | ---: | ---: | ---: |
| Isolated, ordinary affinity | 1/1 | 16.39 s | 31.27 s |
| Isolated, one logical CPU | 1/1 | 29.14 s | 28.55 s |
| Four concurrent, ordinary affinity | 4/4 | 34.28–37.37 s | 30.43–37.22 s each |
| Four concurrent, all on one CPU | 0/4 | 46.07–46.21 s | 11.08–11.21 s each |

The one-CPU stress establishes that CPU contention alone is sufficient
to exhaust the fixed wall budget. Under normal isolated conditions the
same firmware and emulator completed. All sampled Renode children
disappeared when their runners exited, including on timeout. No failure
was observed from a runner synchronization defect or a surviving child.
Those observations cover this workload. The historical instance still
lacks enough diagnostics to identify its specific stalled phase.

Run the reproducer from the repository root:

```sh
python3 tests/setup/discovery_contention.py --output setup/out/discovery-contention
```

The one-CPU stress group deliberately creates overload. It reports
the outcomes rather than treating a timeout as a successful discovery.
Run the stress separately from pilot verification.

## Runner changes

The 45 s limit remains. Renode discovery now logs the beginning of model
and platform loading, platform readiness, and each of five completed
snapshots. On timeout the job retains any partial probe captures alongside
the Renode log. The setup integration test copies the failed job into
ignored `setup/out/discovery-timeouts/` before removing its temporary
directory. The serial pilot command runs the integration suites one at
a time and stops on the first unexpected failure. It performs no retries.

```sh
bash tests/setup/pilot.sh setup/out/pilot
```

A repeat with the new markers completed all five snapshots in isolation
and produced identical discovery snapshots. Under the same one-CPU
stress, all four jobs last reported **loading models and platform**.
None reached the marker before the first capture. This identifies the
pre-capture phase for the reproduced timeouts. A separate injected-timeout
check confirmed preservation of a capture that already existed.
The isolated measurements leave useful margin inside 45 s on this host;
the data support serializing the pilot checks while retaining that bound.

See the [recorded measurements](evidence/discovery-contention.json).
