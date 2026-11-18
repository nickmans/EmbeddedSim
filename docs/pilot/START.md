# EmbeddedSim 0.1.0-pilot.1

## First session on Debian 13 x86-64

The outer package includes `manifest.json`, `SHA256SUMS`, the frozen
`source/` tree, `source.bundle`, a compiled `examples/example.elf`, and
verification evidence. From the extracted package directory:

```sh
sha256sum -c SHA256SUMS
sudo apt-get install bash python3 python3-matplotlib curl ca-certificates coreutils patch tar gzip
cd source
bash setup/start.sh --port 8767
```

Use a modern browser. APT's Matplotlib is for demo plots. The recorded
test environment used Matplotlib 3.10.8 and NumPy 2.3.5. The launcher
downloads and checks the two pinned archives in the manifest, about
353 MiB. A populated cache supports `EMBEDDEDSIM_OFFLINE=1`. The
launcher prints the URL after building its local copy of the example.

1. Open **http://127.0.0.1:8767/setup/** on the host running the server.
   For a remote host, forward that port through SSH. A connection
   refusal usually means the launcher needs to finish or the browser
   needs the correct host or port.
2. Select **STM32F407VGT6 · HSI16 robot**, click **Choose ELF**, and
   select `examples/example.elf` from the extracted package. Select the
   **EmbeddedSim example v1** firmware observer for this supplied ELF.
   The **Use example ELF** button instead uses the locally rebuilt copy.
3. Click **Discover pins** with the populated wiring table. Inspect the
   final snapshot. Match left/right PWM to PA0/PA1, direction to PA4/PA5,
   left A/B to PA6/PA7 and right A/B to PB6/PB7. The supplied wiring is
   already set. If it was cleared, select those pins manually or use
   **Use confirmed preset routes** after discovery. Early snapshots may
   show uninitialized peripherals.
4. Set duration to **10.4 s**, select **Prepare live simulation**, and
   wait for **Ready**. Click **Start**. After 1 s virtual time, click
   **Pause**, enter **0.006** in **Right-wheel load**, and click
   **Queue load**. On **Resume**, look for the applied virtual timestamp.
   Let it advance a little and click **Stop**. If the run finishes first,
   **Reset** starts a fresh session. A paused or ready session holds the
   server's single execution slot.
5. Save CSV, events and config, then click **Open recorded replay**.
   Scrub across the applied load. The viewer shows observed PWM and
   direction, model ground truth and the example's optional firmware
   estimates. Reopen a downloaded CSV with **Open CSV**.
6. In a second shell in `source/`, run the fault recovery demo after
   stopping the live session:

   ```sh
   python3 tests/encoder_fault/recovery.py --output setup/out/first-recovery
   ```

   Open `setup/out/first-recovery/encoder-recovery.png` and read both
   `assertions.txt` files. The baseline passes. The faulted child run
   deliberately reports two failures for feedback activity and tracking
   during the fault. The harness as a whole succeeds after confirming
   those exact failures. Missing outputs, a nonzero harness exit,
   trace validation errors, and simulator timeouts need investigation.
   Reuse a new output directory for each run.

The original and isolated recovery demonstrations remain separate. In
the isolated run the restored speed loop met the declared 1 rad/s
criterion under the unchanged command. The count and odometry errors
persisted. [Recovery evidence](../encoder-recovery.md)

## Scope and known issues

Real Cortex-M4 firmware instructions run in Renode and drive emulated
peripherals. A two-wheel motor and chassis model closes the loop through
quadrature feedback. Digital encoder faults are injected at the GPIO
boundary, and the same ELF, configuration and event log reproduce the
recorded run. The motor parameters are illustrative. Rolling is ideal,
drivers are averaged, and collision, slip and electrical wire-fault
behavior are outside the model. Hardware accuracy and cycle accuracy
remain unvalidated.

The server listens on local loopback and runs one job at a time. Robot
scenarios cover 0.01–30 virtual seconds. Discovery covers 0.01–3 virtual
seconds and has a 45 s emulator wall budget. Run discovery and the pilot
checks serially on a quiet host. Sustained real-time execution is
unqualified. A contention timeout can occur before the first snapshot.
Keep progress logs and partial captures. The earlier historical timeout
could not be diagnosed retrospectively. [Discovery findings](../discovery-timeout.md)

Only the documented HSI16 robot and passive PLL168 discovery routes are
qualified. For firmware and diagnostics, see [Own firmware](OWN-FIRMWARE.md).
Send comments using [Feedback](FEEDBACK.md).
