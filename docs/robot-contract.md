# Differential-drive contract, before evaluating the robot

Target: STM32F407VGT6, HSI16, AHB/1, APB1/1, APB2/2. Left/right PWM
TIM2_CH1/CH2 on PA0/PA1 AF1, PSC15 ARR999 (1 kHz), preloaded CCR1/2.
Encoders: TIM3 PA6/PA7 AF2 and TIM4 PB6/PB7 AF2, mode3, ARR65535.
Control: TIM2 update IRQ28, 1 ms. Direction: PA4/PA5 push-pull GPIO outputs.
Each encoder has 1024 electrical cycles, 4096 x4 counts/revolution; existing
single-motor resolution/profile remains unchanged.

Bridge: DIR=1 positive voltage, DIR=0 negative voltage, V=sign*12*duty.
Zero duty is synchronous short-circuit braking, not coasting. On a direction
transition the model inhibits voltage for 2 ms without resetting current.
Firmware must command zero PWM for 3 ticks before changing DIR and another
3 ticks afterwards. Unsafe direction requests (nonzero measured duty at the
transition) must be zero in the main demonstration.

Illustrative planar robot: mass m=2 kg, yaw inertia Iz=0.04 kg m², wheel
radius r=0.05 m, track b=0.30 m. Direct drive. Each axial inertia
j=Motor.J+Jwheel=0.0002+0.00005=0.00025 kg m². Mass and Iz include the
translating/yawing wheel and motor assemblies, but exclude axial spin already
counted by j. COM is at the axle midpoint. Flat ground, no longitudinal or
lateral slip, rigid chassis, ideal passive support with no drag or work.

Body x forward, y left, positive yaw counterclockwise; initial world pose0.
Positive speed on either wheel means forward rolling, with corresponding
motor wiring. v=r*(wL+wR)/2, yawRate=r*(wR-wL)/b.

M=[a c;c a], a=j+m*r²/4+Iz*r²/b², c=m*r²/4-Iz*r²/b².
M*wdot=[Kt*iL-B*wL-cL*wL, Kt*iR-B*wR-cR*wR].
Each electrical equation is the existing Motor.CurrentRate. Pose derivatives
are xdot=v*cos(yaw), ydot=v*sin(yaw), yawdot=yawRate. Joint RK4 integrates
currents, wheel speeds/angles and pose. PWM is observed from both pins using
the existing trailing 1 ms window; causal boundary coupling is retained.
Main h=25 us, refinement h=12.5 and 6.25 us. No ground truth enters firmware.

Firmware: two signed PI loops, Kp=.04 duty/(rad/s), Ki=.02 duty/rad,
saturation/conditional integration, 20 ms encoder speed window (one count
is 0.0767 rad/s). Initial choice from symmetric effective time constant
(j+m*r²/2)/(B+Kt*Ke/R)=2.037 s and plant gain222.22; PI zero near0.5/s.
Odometry uses incremental encoder distances and midpoint heading, with yaw
wrapped to [-pi,pi). True yaw is unwrapped; comparisons use wrapped errors.

Sequence (seconds, wheel targets rad/s): 0-.2 stop; .2-2 straight10/10;
2-2.8 stop; 2.8-4.4 turn-5/+5; 4.4-5.2 stop; 5.2-7 curve6/10;
7-7.8 stop; 7.8-9.6 reverse-8/-8; 9.6-10.4 stop.
External extra right viscous resistance cR=.0015 N m/(rad/s) on [.8,1.4),
zero otherwise. It opposes actual wheel motion; firmware cannot see it.

Acceptance, fixed before results (no loosening for tuning):

- Additional compiled-firmware paths: two independent 1 ms PWM periods/high
  times within2.1 ns, independent CCR updates including0/100%, TIM2 IRQ count
  deltas/flag clearing, encoder independence/both directions/wrap/CEN/clock
  gate, selected PB6/7 AF/mode routing, PA4/5 BSRR direction levels.
- Pure model: equal/opposite voltages preserve left/right symmetry to1e-10;
  equal actuation straight, opposite actuation in-place, equal negative
  actuation reverse. Curved steady kinematics/arc agree within0.1%.
- Body acceleration/force/yaw torque equations agree within1e-8 relative.
  Energy = magnetic + axial spin + chassis translation/yaw. With known
  electrical work and losses, normalized energy residual <1e-5. Unforced
  braking energy decreases. No double-counting of chassis inertia.
- Main settled wheel mean errors <5% in [1.7,1.95], [4.1,4.35], [6.7,6.95],
  [9.3,9.55]. Stop-window final |wheel speed|<0.5 rad/s. PWM quantization
  and minimum-speed encoder quantization justify5%, rather than perfect
  speed agreement. Odometry max position error<2 cm, wrapped yaw error<0.02 rad.
- Load/no-load runs use identical ELF. Before .8 s their complete traces
  match; afterwards added right resistance increases right current by>0.1 A,
  right duty by>0.02 and visibly lowers right speed/estimate by>0.1 rad/s.
- Signed outputs stay bounded, direction changes obey blanking, encoder
  counters match generated totals modulo65536, IRQ errors=0.
- Refinement vs6.25 us: position max<5 mm, yaw max<0.01 rad and wheel speed
  max<0.5 rad/s. Repeat and pause/resume traces byte-identical. Step bound h+2 ns.

All values are illustrative. Consistency/convergence is not physical validation.
