"""Validation and route capabilities for the version 1 robot scenario."""
import json
import math
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "stm32f407vgt6"
PROFILE = "robot-hsi16-v1"
PWM_SIGNAL_PROFILE = "pwm-signal-pll168-v1"
PRESET = "differential-drive-v1"
PINS = {
    "PA0": ("pwm", "TIM2_CH1", 1),
    "PA1": ("pwm", "TIM2_CH2", 1),
    "PA4": ("direction", None, None),
    "PA5": ("direction", None, None),
    "PA6": ("encoder_a", "TIM3_CH1", 2),
    "PA7": ("encoder_b", "TIM3_CH2", 2),
    "PB6": ("encoder_a", "TIM4_CH1", 2),
    "PB7": ("encoder_b", "TIM4_CH2", 2),
}
ENDPOINTS = {f"{side}.{role}": role for side in ("left", "right") for role in
             ("pwm", "direction", "encoder_a", "encoder_b")}
BODY_LIMITS = {
    "mass_kg": (0.25, 20), "yaw_inertia_kg_m2": (0.005, 1),
    "wheel_radius_m": (0.015, 0.15), "track_width_m": (0.14, 1),
    "wheel_inertia_kg_m2": (0, 0.005),
}
MOTOR = dict(resistance_ohm=2, inductance_H=0.005, back_emf_V_per_rad_s=0.05,
             torque_Nm_per_A=0.05, inertia_kg_m2=0.0002, viscous_Nms=0.0001)
DRIVER = dict(supply_V=12, pwm_window_s=0.001, direction_blank_s=0.002)
ENCODER = dict(counts_per_revolution=4096)


class SetupError(ValueError):
    pass


def default_config():
    return json.loads((ROOT / "setup/default.json").read_text())


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise SetupError(f"{label} must contain exactly: {', '.join(expected)}.")
    return value


def number(value, low, high, label):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise SetupError(f"{label} must be a finite number between {low} and {high}.")
    return value


ENCODER_CHANNELS = ("left.a", "left.b", "right.a", "right.b")


def fault_level(value, allow_clear=False):
    if value is None and allow_clear:
        return value
    if type(value) != int or value not in (0, 1):
        raise SetupError("Encoder fault level must be 0 or 1 (or null to clear in live mode).")
    return value


def fault_channel(value):
    if value not in ENCODER_CHANNELS:
        raise SetupError("Encoder channel must be left.a, left.b, right.a or right.b.")
    return ENCODER_CHANNELS.index(value)


def fault_time_ns(value, duration):
    number(value, 0, duration, "Encoder fault time (s)")
    ticks = Decimal(str(value)) * 1_000_000_000
    if ticks % 25000:
        raise SetupError("Encoder fault times must lie on the 25 µs physics grid.")
    return int(ticks)


def fault_evidence(config):
    scenario = config["scenario"]
    return scenario.get("encoder_fault_evidence", False) or bool(scenario.get("encoder_faults"))


def validate_faults(scenario, duration):
    if type(scenario.get("encoder_fault_evidence", False)) != bool:
        raise SetupError("encoder_fault_evidence must be a boolean.")
    faults = scenario.get("encoder_faults", [])
    if not isinstance(faults, list) or len(faults) > 16:
        raise SetupError("encoder_faults must be an array of at most 16 intervals.")
    ends = {}
    for fault in faults:
        fields(fault, ("channel", "level", "start_s", "end_s"), "Encoder fault")
        channel = fault_channel(fault["channel"])
        fault_level(fault["level"])
        start = fault_time_ns(fault["start_s"], duration)
        end = fault_time_ns(fault["end_s"], duration)
        if start < ends.get(channel, 0) or end <= start:
            raise SetupError("Encoder faults must be ordered and non-overlapping per channel, with positive duration.")
        ends[channel] = end


def validate(config, discovery=False):
    if isinstance(config, dict) and config.get("target") == {"part": TARGET, "profile": PWM_SIGNAL_PROFILE}:
        if not discovery:
            raise SetupError("The pwm-signal-pll168-v1 profile supports discovery only. Its capture inputs and four PWM outputs do not match the differential-drive robot.")
        if {"robot", "world", "wiring", "scenario"} & config.keys():
            raise SetupError("The PWM signal profile has no robot connections or RAM observer. Use a configuration containing only version and target.")
        fields(config, ("version", "target"), "PWM signal configuration")
        if type(config["version"]) != int or config["version"] != 1:
            raise SetupError("Only configuration version 1 is supported.")
        return config
    fields(config, ("version", "target", "robot", "world", "wiring", "scenario"), "Configuration")
    if type(config["version"]) != int or config["version"] != 1:
        raise SetupError("Only configuration version 1 is supported.")
    if config["target"] != {"part": TARGET, "profile": PROFILE}:
        raise SetupError("Select STM32F407VGT6 and the robot-hsi16-v1 peripheral profile explicitly.")
    if config["world"] != {"type": "empty-flat-floor"}:
        raise SetupError("Select the empty flat floor world.")
    robot = fields(config["robot"], ("preset", "body", "motors", "drivers", "encoders"), "Robot")
    if robot["preset"] != PRESET:
        raise SetupError("Only the differential-drive-v1 robot preset is supported.")
    for key, expected in (("motors", MOTOR), ("drivers", DRIVER), ("encoders", ENCODER)):
        actual = fields(robot[key], expected, key)
        if any(type(actual[name]) not in (int, float) or actual[name] != value for name, value in expected.items()):
            raise SetupError(f"{key} use the fixed qualified preset values.")
    body = fields(robot["body"], BODY_LIMITS, "Robot body")
    for key, bounds in BODY_LIMITS.items():
        number(body[key], *bounds, key)

    wiring = fields(config["wiring"], ENDPOINTS, "Wiring")
    used = {}
    for endpoint, role in ENDPOINTS.items():
        pin = wiring[endpoint]
        if pin is None and discovery:
            continue
        if pin is None:
            raise SetupError(f"Connect required endpoint {endpoint} before running.")
        if not isinstance(pin, str) or pin not in PINS or PINS[pin][0] != role:
            supported = ", ".join(p for p, (kind, *_rest) in PINS.items() if kind == role)
            raise SetupError(f"{endpoint}: {pin!r} is unsupported here. Supported routes: {supported}.")
        if pin in used:
            raise SetupError(f"{pin} is already connected to {used[pin]}; disconnect it before wiring {endpoint}.")
        used[pin] = endpoint
    for side in ("left", "right"):
        a, b = (wiring[f"{side}.encoder_{phase}"] for phase in "ab")
        if (a is None) != (b is None):
            raise SetupError(f"{side} encoder requires both A/B pins, or both disconnected during discovery.")
        if a and a[:2] != b[:2]:
            raise SetupError(f"{side} encoder A/B must share the same qualified timer pair.")

    scenario = config["scenario"]
    optional = ("encoder_faults", "encoder_fault_evidence")
    required = ("duration_s", "initial_pose", "loads", "observer")
    fields(scenario, required + tuple(key for key in optional if isinstance(scenario, dict) and key in scenario), "Scenario")
    duration = number(scenario["duration_s"], 0.01, 30, "Duration (s)")
    validate_faults(scenario, duration)
    pose = fields(scenario["initial_pose"], ("x_m", "y_m", "heading_rad"), "Initial pose")
    for key, value in pose.items():
        number(value, -10, 10, key)
    if scenario["observer"] not in ("none", "example-v1"):
        raise SetupError("Choose no observer or the EmbeddedSim example-v1 observer.")
    loads = scenario["loads"]
    if not isinstance(loads, list) or len(loads) > 16:
        raise SetupError("Loads must be an array with at most 16 events.")
    previous_end = 0
    for event in loads:
        fields(event, ("start_s", "end_s", "left_Nms", "right_Nms"), "Load event")
        start = number(event["start_s"], 0, duration, "Load start (s)")
        end = number(event["end_s"], 0, duration, "Load end (s)")
        if start < previous_end or end <= start:
            raise SetupError("Load events must have positive duration, be ordered, and avoid overlap.")
        previous_end = end
        for side in ("left", "right"):
            number(event[f"{side}_Nms"], 0, 0.02, f"{side} drag (N·m/(rad/s))")
    return config


def load_config(path, discovery=False):
    try:
        return validate(json.loads(Path(path).read_text()), discovery)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SetupError(f"Could not read configuration: {error}") from error
