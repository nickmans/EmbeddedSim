# External tester guide

## Install and launch

The local setup workflow was verified on **Debian 13 Linux x86-64** in
a separate Git checkout whose path contained spaces, with an empty tool
cache on first launch and cached offline operation afterward. It
uses Bash, Python 3.10 or later, curl, tar with gzip, GNU coreutils, GNU
patch, and a modern browser. Install these with your distribution's package
manager. Renode's portable build supplies its .NET runtime and uses Linux
system libraries. STM32CubeIDE and CubeMX are unnecessary. Windows and
macOS are outside this qualification.

From a fresh checkout, run:

```sh
bash setup/start.sh --port 8767
```

Open **http://127.0.0.1:8767/setup/** from a browser on the server machine.
For a remote Linux machine, use SSH local port forwarding such as
`ssh -L 8767:127.0.0.1:8767 user@sim-host`. Use the matching loopback URL
on your client. The server listens on IPv4 loopback. Keep it local.

First launch downloads SHA-256-pinned Renode 1.17.0 and xPack Arm GNU
Toolchain 15.2.1-1.1 from their GitHub releases (about 353 MiB combined),
checks both archives, extracts the tools, and builds the example ELF.
Later launches reuse the archives and extracted tools. For cached offline
use, launch with `EMBEDDEDSIM_OFFLINE=1`. An empty offline cache reports
which archive is missing.

| Setting | Default and purpose |
| --- | --- |
| `EMBEDDEDSIM_CACHE` | `${XDG_CACHE_HOME:-$HOME/.cache}/embeddedsim` for the dependencies and bootstrap runtime state. |
| `EMBEDDEDSIM_TOOLS_DIR`, `EMBEDDEDSIM_DOWNLOADS_DIR` | Override the cache's `tools` and `downloads` directories independently. |
| `EMBEDDEDSIM_ARTIFACTS` | Directory for browser job artifacts. Defaults to ignored `setup/out/jobs/`. CLI output uses its explicit `--output` argument. |
| `RENODE_ROOT`, `ARM_GCC` | Override the runtime Renode directory or example compiler executable. Bootstrapping still provisions its pinned distributions. |

Use absolute paths for overrides. For example:

```sh
EMBEDDEDSIM_CACHE="$HOME/.cache/embeddedsim" \
EMBEDDEDSIM_ARTIFACTS="$HOME/embeddedsim-runs" \
bash setup/start.sh --port 8871
```

The setup workflow keeps generated artifacts separate from the checked-in
reports and evidence. The historical hardware and plotting test scripts
have additional dependencies and some still expect the original workspace
tool paths. Node and Chromium are needed only for the automated performance
and browser checks.

## First run checklist

1. Select **STM32F407VGT6 · HSI16 robot**, click **Use example ELF**, and
   keep the preset wiring. The example selection enables its firmware
   observer. Click **Discover pins** to inspect GPIO, alternate
   functions, clocks, and timer snapshots.
2. Set the scenario duration. Use **Prepare live simulation**, wait for
   **Ready**, and click **Start**. Confirm that virtual time and the robot
   scene advance. Pause, queue a right-wheel load, then resume and inspect
   its recorded virtual application time.
3. Stop or let the session complete. Save the CSV, events, config and
   Renode log. Use **Open recorded replay** and scrub through it. To reopen
   a saved file after a server restart, choose **Open CSV** in the replay
   viewer. **Run for replay** in setup is also available.
4. Try a compatible external ELF with the firmware observer set to
   **None** unless the ELF implements the example telemetry ABI. Confirm
   the wiring and clock profile against the firmware first. See the
   [setup reference](../setup/README.md) for exact routes.

## Supported profile

The two-wheel robot has direct-drive motors and quadrature encoders on an
empty floor. Its HSI16 profile qualifies TIM2 PWM on PA0/PA1, direction
on PA4/PA5, TIM3 encoders on PA6/PA7 and TIM4 encoders on PB6/PB7.
The separate PLL168 profile provides passive discovery for the qualified
TIM2 capture, TIM3 PWM, and direction/brake GPIO routes of the public
third-party ELF. Its four PWM outputs and capture inputs have no robot
preset. See the [third-party qualification](third-party-pwm-qualification.md)
and [timing qualification](stm32f407-timebase.md).

Ground-truth pose, wheel speed, and motor current are model outputs.
PWM and direction are observed emulator signals. The optional example
observer supplies firmware setpoints and estimated wheel speed and
odometry. The physics uses ideal rolling, averaged motor drivers and
illustrative parameters. There is no slip, collision handling, physical
hardware validation, cycle-accuracy claim, or real-time guarantee.

Only one execution slot is available per server. Robot runs allow up
to 30 virtual seconds. A ready or paused live session reserves the
slot. Arbitrary routes and peripherals, bootloaders and external memory
are outside qualification. TIM9 active operation, ITM/SWO delivery,
SRAM bit-band and broader architectural features remain unqualified.
Peripheral bit-band and clock/SysTick coverage are listed in the timing
report. Renode warnings are surfaced when available. The absence of
warnings gives no guarantee that all hardware accesses are supported.

## Report a failing external ELF

Include the repository revision, OS and architecture, Python and Renode
versions, and compiler/build flags if available. Include the ELF SHA-256
and share the exact binary only if allowed. Attach the exported config
and wiring, selected profile, discovery result or live event log, and
Renode log. The browser log link shows the tail. The job directory
holds the complete captured log within the live log size cap. Describe
the exact launch and reproduction steps, observed behavior, expected
registers or signals, and the first virtual time where they diverged.


## External pilot checklist

1. Reserve the machine for the pilot checks and run
   `bash tests/setup/pilot.sh setup/out/pilot` from the repository root
   with the pinned tools and Matplotlib available.
2. Confirm the baseline has passing assertions. Confirm the faulted run
   reports the planned failures and inspect its reconnection and later
   commanded-stop windows separately. Retain both CSVs and the exact ELF.
3. Start the setup UI, choose the qualified clock profile and wiring, and
   run discovery once. On a timeout, retain the Renode progress log,
   any partial capture, and notes on other CPU-intensive jobs before
   attempting an isolated run.
4. For live fault evidence, save the recording, configuration, and event
   log. Reproduce with the same ELF before comparing outcomes.

See the [recovery experiment](encoder-recovery.md) and
[discovery investigation](discovery-timeout.md).
