"""Focused configuration, ELF, wiring, and Renode workflow checks."""
import copy
import csv
from pathlib import Path
import shutil
import struct
import sys
from tempfile import TemporaryDirectory, mkdtemp
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "setup"))

from config import SetupError, default_config, load_config, validate
from elf import validate_elf
from runner import DiscoveryTimeout, build_example, run_job


class ValidationTests(unittest.TestCase):
    def test_wiring_roles_duplicates_and_optional_discovery(self):
        for pin, error in (("PA1", "already connected"), ("PA4", "unsupported here"), ("PA8", "unsupported here")):
            config = default_config()
            config["wiring"]["left.pwm"] = pin
            with self.subTest(pin=pin), self.assertRaisesRegex(SetupError, error):
                validate(config)
        config = default_config()
        config["wiring"] = dict.fromkeys(config["wiring"])
        validate(config, discovery=True)
        with self.assertRaisesRegex(SetupError, "Connect required endpoint"):
            validate(config)
        config["wiring"].update({"left.encoder_a": "PA6", "left.encoder_b": "PB7"})
        with self.assertRaisesRegex(SetupError, "same qualified timer"):
            validate(config, discovery=True)

    def test_numeric_and_target_validation(self):
        config = default_config()
        config["target"]["part"] = "stm32f407zet6"
        with self.assertRaisesRegex(SetupError, "Select STM32F407VGT6"):
            validate(config)
        for value in (-1, "2", True, float("nan"), 1 << 3000):
            config = default_config()
            config["robot"]["body"]["mass_kg"] = value
            with self.subTest(value=value), self.assertRaisesRegex(SetupError, "mass_kg"):
                validate(config)
        config = default_config()
        config["scenario"]["loads"] *= 2
        with self.assertRaisesRegex(SetupError, "avoid overlap"):
            validate(config)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = TemporaryDirectory(prefix="setup-check-")
        cls.addClassCleanup(cls.work.cleanup)
        cls.root = Path(cls.work.name)
        cls.images = {}
        for name, source in (("example", "firmware/robot/controller.c"),
                             ("minimal", "tests/setup/minimal.c"),
                             ("incomplete", "tests/setup/incomplete.c")):
            path = cls.root / (name + ".elf")
            build_example(path, source)
            cls.images[name] = path.read_bytes()

    def job(self, name, image, config, operation="run", seconds=0.5):
        path = self.root / name
        try:
            result = run_job(self.images[image], config, path, operation, seconds)
        except DiscoveryTimeout as error:
            retained = ROOT / "setup/out/discovery-timeouts"
            retained.mkdir(parents=True, exist_ok=True)
            destination = Path(mkdtemp(prefix=f"{name}-", dir=retained))
            shutil.copytree(path, destination, dirs_exist_ok=True)
            raise DiscoveryTimeout(f"Discovery timed out. Retained artifacts in {destination}.") from error
        return path, result

    def test_elf_header_load_memory_and_thumb_reset(self):
        image = self.images["minimal"]
        self.assertTrue(validate_elf(image))
        with self.assertRaisesRegex(SetupError, "ELF32"):
            validate_elf(b"not really firmware")
        off, = struct.unpack_from("<I", image, 28)
        vector, = struct.unpack_from("<I", image, off + 4)
        for offset, fmt, value, error in (
            (18, "<H", 62, "ARM EABI5"),
            (off + 8, "<I", 0x40000000, "runtime range"),
            (off + 12, "<I", 0x40000000, "load address"),
            (vector, "<I", 0x40020000, "initial stack"),
            (vector + 4, "<I", 0x08000000, "Reset vector"),
            (24, "<I", 0x08000000, "ELF entry"),
        ):
            altered = bytearray(image)
            struct.pack_into(fmt, altered, offset, value)
            with self.subTest(offset=offset), self.assertRaisesRegex(SetupError, error):
                validate_elf(altered)

    def test_discovery_observes_pwm_encoder_direction_and_incomplete_startup(self):
        attached = default_config()
        _, result = self.job("discover-attached", "example", attached, "discover")
        self.assertEqual([item["time_s"] for item in result["snapshots"]], [0, .125, .25, .375, .5])
        initial, idle, _, _, final = result["snapshots"]
        self.assertFalse(initial["pins"]["PA0"]["qualified"])
        self.assertTrue(all(pin["qualified"] for pin in final["pins"].values()))
        self.assertTrue(final["clock_profile_matches"])
        self.assertEqual(idle["pins"]["PA0"]["activity"]["duty"], 0)
        self.assertIsNone(idle["pins"]["PA0"]["activity"]["period_s"])
        self.assertAlmostEqual(final["pins"]["PA0"]["activity"]["period_s"], 0.001, places=8)
        self.assertEqual(final["pins"]["PA1"]["peripheral"], "TIM2_CH2")
        self.assertEqual(final["pins"]["PA4"]["activity"]["level"], "high")
        self.assertEqual(final["pins"]["PB7"]["timer"]["sms"], 3)
        self.assertEqual(final["pins"]["PA6"]["role"], "input")

        disconnected = copy.deepcopy(attached)
        disconnected["wiring"] = dict.fromkeys(disconnected["wiring"])
        _, result = self.job("discover-disconnected", "minimal", disconnected, "discover", .04)
        pins = result["snapshots"][-1]["pins"]
        self.assertAlmostEqual(pins["PA0"]["activity"]["duty"], .25, places=5)
        self.assertEqual(pins["PA1"]["activity"]["duty"], 1)
        self.assertIsNone(pins["PA1"]["activity"]["period_s"])
        _, result = self.job("discover-incomplete", "incomplete", disconnected, "discover", .04)
        self.assertAlmostEqual(result["snapshots"][-1]["time_s"], .04)
        self.assertTrue(all(not pin["qualified"] and pin["activity"] is None
                            for pin in result["snapshots"][-1]["pins"].values()))

    def test_external_scenario_reproduces_and_load_affects_same_elf(self):
        config = default_config()
        config["scenario"].update(duration_s=.5, initial_pose={"x_m": .2, "y_m": -.1, "heading_rad": .5},
                                  loads=[dict(start_s=.1, end_s=.4, left_Nms=0, right_Nms=.006)])
        config["robot"]["body"]["wheel_radius_m"] = .06
        loaded, result = self.job("loaded", "minimal", config)
        repeat, reproduced = self.job("repeat", "minimal", load_config(loaded / "config.json"))
        self.assertEqual(result, reproduced)
        self.assertEqual((loaded / "recording.csv").read_bytes(), (repeat / "recording.csv").read_bytes())
        config["scenario"]["loads"] = []
        unloaded, baseline = self.job("unloaded", "minimal", config)
        self.assertEqual(result["elf_sha256"], baseline["elf_sha256"])
        self.assertEqual(result["samples"], 500)
        before, after = readings(loaded), readings(unloaded)
        self.assertEqual(before[0]["x_m"], .2)
        self.assertEqual(before[0]["wheel_radius_m"], .06)
        self.assertEqual(before[:99], after[:99])
        self.assertNotIn("odom_x_m", before[0])
        self.assertNotIn("reference_l_rad_s", before[0])
        self.assertNotIn("fw_tick", before[0])
        self.assertGreater(before[-1]["x_m"], .2)
        self.assertLess(before[399]["wr_rad_s"], after[399]["wr_rad_s"])
        self.assertEqual(before[250]["duty_r"], 1)
        self.assertGreater(abs(before[250]["encoder_r"]), 0)
        self.assertEqual(before[250]["tim4_counter"], int(before[250]["encoder_r"]) % 65536)

        config["wiring"].update({"left.pwm": "PA1", "right.pwm": "PA0",
                                 "left.encoder_a": "PB6", "left.encoder_b": "PB7",
                                 "right.encoder_a": "PA6", "right.encoder_b": "PA7"})
        swapped, _ = self.job("swapped", "minimal", config)
        row = readings(swapped)[250]
        self.assertAlmostEqual(row["duty_l"], after[250]["duty_r"], places=6)
        self.assertAlmostEqual(row["duty_r"], after[250]["duty_l"], places=6)
        self.assertEqual(row["tim4_counter"], int(row["encoder_l"]) % 65536)
        self.assertEqual(row["tim3_counter"], int(row["encoder_r"]) % 65536)
        # The built-in observer is deliberately opt-in, including for uploaded example images.
        config["scenario"]["observer"] = "example-v1"
        with self.assertRaisesRegex(SetupError, "Invalid EmbeddedSim example"):
            self.job("wrong-observer", "minimal", config)


def readings(path):
    with (path / "recording.csv").open() as handle:
        return [{key: float(value) for key, value in row.items()} for row in csv.DictReader(handle)]


if __name__ == "__main__":
    unittest.main(verbosity=2)
