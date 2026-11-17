# First motor loop: contract fixed before controller tuning

Illustrative SI parameter set (not measured hardware): R=2 ohm, L=0.005 H,
Ke=0.05 V/(rad/s), Kt=0.05 N m/A, J=0.0002 kg m²,
b=0.0001 N m/(rad/s), supply=12 V. Positive current produces positive
torque; positive external load subtracts torque. Initial i=omega=theta=0
except an explicit external reverse shaft impulse at 0.05 s (omega=-40 rad/s).

The forward averaged bridge applies V=12*duty with synchronous short-circuit
braking at zero duty (V=0, **not coasting**). Current can be negative. Supply
is ideal and can absorb regeneration. Switching ripple, dead time, losses,
battery, thermal effects and hardware validation are outside this model.

RK4 with constant interval inputs integrates the electrical/mechanical ODE.
Reference physics step is 25 us, with 12.5 and 6.25 us comparisons. Encoder:
256 electrical cycles/revolution, 1024 x4 counts/revolution. Continuous angle
is retained; the unbounded signed count is floor(theta*1024/(2*pi)).

PWM duty is the high-time fraction in a trailing 1 ms window, derived only
from PA0 edges and current pin level. Startup is low. Constant levels become
0 or 1 after one window, without requiring a new edge. Window delay <=1 ms,
plus at most one physics step; no CCR/desired-speed shortcut is permitted.

Firmware uses a 10 ms moving encoder-count window (one count = 0.614 rad/s),
TIM4 1 ms PI updates, saturation [0,1] and conditional-integration anti-windup.
Initial analytical gains: Kp=0.006 duty/(rad/s), Ki=0.05 duty/rad. At low
frequency the plant is approximately 222.22/(0.14815*s+1), making a ~0.6 s
settling budget reasonable. Gains may be tuned; the following thresholds
must not be loosened to accommodate results.

Scenarios/acceptance:

- Pure model: analytical steady speed/current at 50% duty, both no load and
  0.04 N m load, relative error <1e-5 after 5 s. RK4 transient error decreases
  by >=8x for each step halving (1, 0.5, 0.25 ms versus a 15.625 us reference).
- Open loop: zero until 0.1 s, duty 0.5 until 0.8 s, duty 1 until 1.0 s,
  then zero until 2.0 s. Measured duty agrees within 0.002 after window delay;
  final braking speed <1 rad/s and measured duty zero.
- Closed loop: reference 60 rad/s at 0.1 s, 100 at 0.9 s, zero at 3.2 s,
  finish at 4.0 s. Mean true and estimated steady error <2% in windows
  [0.7,0.85], [1.4,1.55], [2.2,2.35], [3.0,3.15] s. Overshoot <15% for
  each positive step. Duty must stay in [0,1]. Final zero-drive speed <2 rad/s.
- External load=0.04 N m on [1.6,2.4) s, unknown to firmware. Speed must dip
  visibly by >=1 rad/s but stay >80 rad/s; loaded steady duty must rise by
  >0.10 from unloaded. Removal overshoot <15%, recovered by 3.0 s.
- Timing: no retroactive injection. Quantize shaft crossings to the next
  physics boundary (latency <=h), preserve every edge including multiple
  crossings. Smaller steps must change matched 1 ms ground-truth speed
  samples by <1 rad/s max and <0.25 rad/s RMS. Encoder cumulative angle/count
  error <one count; final actual TIM3 CNT equals generated count modulo 65536.
- Same inputs must reproduce byte-identical CSV traces. Pausing at 1.8 s
  and resuming must preserve the trace/state. Real encoder reads must show
  forward wrap and reverse underflow using initial CNT offsets 65530 and 2.
- A no-load counterfactual uses the identical closed-loop ELF and must match
  the loaded run exactly before 1.6 s. After load application, estimated and
  true speed must fall relative to that run and commanded duty rise by >0.10.
- Saturation diagnostic: feasible reference 200 rad/s at 0.1 s, then 60 at
  0.8 s; output must actually reach 1, remain bounded, integral stay below
  0.95, and mean true/estimated error on [1.7,1.9] s be <2% of 60 rad/s.

The independent model is numerical physics. Convergence and internal
consistency do not constitute physical-hardware validation.
