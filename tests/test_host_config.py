import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "host_config.py"
SPEC = importlib.util.spec_from_file_location("host_config", MODULE_PATH)
assert SPEC and SPEC.loader
host_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host_config)


class HostConfigTests(unittest.TestCase):
    def test_boolean_values_are_strict(self):
        self.assertTrue(host_config.boolean("yes", "TEST"))
        self.assertFalse(host_config.boolean("OFF", "TEST"))
        with self.assertRaises(host_config.ConfigError):
            host_config.boolean("maybe", "TEST")

    def test_disk_exclude_uses_resolved_kernel_names(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nvme9n1"
            target.touch()
            link = Path(directory) / "stable-device"
            link.symlink_to(target)
            expression = host_config.build_disk_exclude([str(link)])
        self.assertIn("nvme9n1", expression)
        self.assertTrue(expression.startswith(host_config.BASE_DISK_EXCLUDE))

    def test_empty_protected_regex_matches_nothing(self):
        self.assertEqual(host_config.protected_metric_regex([]), "a^")

    def test_defaults_are_fail_closed(self):
        config = host_config.defaults({})
        self.assertEqual(config["ENABLE_NVIDIA_GPU"], "false")
        self.assertEqual(config["GPU_IDENTITY_MODE"], "alias")
        self.assertEqual(config["ENABLE_SMART"], "false")
        self.assertEqual(config["FAN_METRICS_MODE"], "disabled")
        self.assertEqual(config["PROTECTED_DEVICE_PATHS"], "")

    def test_env_parser_does_not_execute_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            marker = Path(directory) / "must-not-exist"
            path.write_text(f"SAFE=$(touch {marker})\n", encoding="utf-8")
            values = host_config.read_env(path)
            self.assertEqual(values["SAFE"], f"$(touch {marker})")
            self.assertFalse(marker.exists())

    def test_services_follow_feature_flags(self):
        config = host_config.defaults({})
        self.assertEqual(
            host_config.services(config, "normal"),
            ["node-exporter", "prometheus", "grafana"],
        )
        config["ENABLE_NVIDIA_GPU"] = "true"
        config["ENABLE_SMART"] = "true"
        config["SMART_DEVICE_HOST"] = "/dev/example"
        self.assertIn("fast-gpu-exporter", host_config.services(config, "normal"))
        self.assertIn("smartctl-exporter", host_config.services(config, "normal"))

    def test_nvme_protocol_is_explicit_after_device_rename(self):
        self.assertEqual(host_config.default_smart_device_type("/dev/nvme7n1"), "nvme")
        self.assertEqual(host_config.default_smart_device_type("/dev/sdz"), "auto")

    def test_host_label_rejects_template_injection(self):
        config = host_config.defaults({})
        config["HOST_LABEL"] = 'bad"label'
        with self.assertRaises(host_config.ConfigError):
            host_config.validate_scalar_config(config)


if __name__ == "__main__":
    unittest.main()
