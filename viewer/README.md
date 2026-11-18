# Recorded simulation replay

From the repository root, generate the firmware-driven demo and serve the viewer
with one command.

```sh
bash viewer/demo.sh
```

Open [the local viewer](http://127.0.0.1:8765/viewer/) in a modern browser.
Pass a port as the first argument if 8765 is in use. The command runs the
existing main robot scenario, verifies the trace, and serves static files
on loopback. Stop the server with Ctrl+C. If the recording already exists,
`python3 -m http.server --bind 127.0.0.1 8765` from the repository root
serves it immediately. Node is only needed for the viewer's tests.

Use **Open CSV** to select another robot recording. The browser reads the
file locally. **Load demo** reloads the generated `tests/robot/out/main.csv`.
To share a recording, send the CSV to someone who has the viewer, or serve
the static viewer files and demo CSV together with the same relative paths.
There are no runtime packages or remote assets.

## Robot CSV v1

The viewer calls the existing unversioned [RobotLoop exporter](../integration/renode/RobotLoop.cs)
format v1. It recognizes the schema by header names and accepts all six
firmware-driven robot case exports. The independent `physics.csv` uses a
different schema. Columns may be reordered. Each row contains finite decimal
numbers, with optional exponential notation or quotes around scalar cells.
The first four columns below are required. Optional signals appear when
their columns are present. Additional numeric columns are accepted.

| Columns | Units | Source |
| --- | --- | --- |
| `time_s` | s | Simulation clock, strictly increasing |
| `x_m`, `y_m`, `heading_rad` | m, m, rad | Model ground truth |
| `odom_x_m`, `odom_y_m`, `odom_heading_rad` | m, m, rad | Firmware encoder-derived pose estimate |
| `wl_rad_s`, `wr_rad_s` | rad/s | Model wheel speeds |
| `estimate_l_rad_s`, `estimate_r_rad_s` | rad/s | Firmware encoder-derived wheel speed estimates |
| `reference_l_rad_s`, `reference_r_rad_s` | rad/s | Firmware wheel speed commands |
| `duty_l`, `duty_r` | fraction, shown as % | Observed PWM pin high time over the trailing 1 ms |
| `dir_l`, `dir_r` | −1 low, +1 high | Observed direction GPIO, signed bridge input |
| `il_A`, `ir_A` | A | Model electrical state |
| `right_drag_Nms` | N·m/(rad/s) | Applied external right-wheel viscous coefficient |
| `resistance_l_Nm`, `resistance_r_Nm` | N·m | Signed resistance term subtracted by the model |

With all three odometry columns, the viewer draws the firmware path and derives
Euclidean position error and the wrapped signed heading difference
(firmware minus model). The odometry path is dashed and drawn at its recorded
coordinates. World +x points right, +y up, and positive yaw counterclockwise.
The schematic uses the 0.30 m center-to-center track and 0.05 m wheel radius in
the [robot contract](../docs/robot-contract.md). The axle, wheel strokes, and
forward arrow depict orientation without assuming chassis dimensions.

The cursor uses recorded simulation timestamps. At intermediate times the
schematic interpolates model x/y linearly and takes the shortest arc between
heading samples (adjacent samples must be less than half a turn apart to
resolve the arc). The telemetry panel holds the latest sample at or before the
cursor, including the measurements and firmware frame captured on that row.
Plots connect sampled values for readability and use steps for GPIO levels.
Click or drag a plot to seek. Playback ends at the final sample, and the
duration is the last timestamp minus the first.

The model assumes ideal rolling with no slip or collisions, averaged motor
drivers, and illustrative physical parameters. It has not been validated
against physical hardware.

## Checks

After generating the demo, run `node --test viewer/trace.test.mjs` from the
repository root. The simulation regression remains `bash tests/robot/check.sh`.
