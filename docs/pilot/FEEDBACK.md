# Pilot feedback and bug report

- What were you trying to test?
- Could you complete the supplied walkthrough without assistance? Where did you stop?
- Where did setup or wiring become unclear?
- Did your own ELF initialize and produce the expected signals? Which signals or registers differed?
- What useful issue did the simulator reveal?
- Which missing capability prevented further use?
- Would you use it again on an actual project? Why or why not?

For a failed run, include:

- Package version and source revision from the manifest. Was the source changed?
- Host OS, architecture, CPU, memory or cgroup limits, Python, Renode, and compiler versions.
- Firmware target, clock tree, build flags if shareable, and ELF SHA-256.
- Selected profile, exported config and pin mapping, job ID, and running workload.
- Exact steps, expected and observed results, and first divergent virtual time if known.
- Relevant log and partial capture, result JSON, recording or event log, with SHA-256 hashes.

Stage a copy of the files, inspect the archive contents, and share only
what you have authorization to disclose. See [Collect diagnostics](OWN-FIRMWARE.md#collect-diagnostics).
