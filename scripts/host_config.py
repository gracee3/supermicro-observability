#!/usr/bin/env python3
"""Host-profile configuration and validation using only the standard library."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT / ".env"
PROM_TEMPLATE = PROJECT / "prometheus" / "prometheus.yml.in"
RUNTIME = PROJECT / "runtime"
PROM_RUNTIME = RUNTIME / "prometheus"
FILE_SD = PROM_RUNTIME / "file_sd"
LOCAL_TEXTFILE = RUNTIME / "textfile_collector"

BASE_DISK_EXCLUDE = r"^(ram|loop|fd|sr|zram)[0-9]+$"
VALID_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
VALID_LABEL = re.compile(r"^[A-Za-z0-9_.-]+$")
VALID_PROFILES = {"generic", "supermicro-x11spa-tf"}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}

CONFIG_ORDER = [
    "GRAFANA_ADMIN_PASSWORD",
    "OBSERVABILITY_UID",
    "OBSERVABILITY_GID",
    "HOST_LABEL",
    "PLATFORM_PROFILE",
    "ENABLE_NVIDIA_GPU",
    "GPU_IDENTITY_MODE",
    "GPU_IDENTITY_SALT",
    "ENABLE_SMART",
    "SMART_DEVICE_HOST",
    "SMART_DEVICE_TYPE",
    "PROTECTED_DEVICE_PATHS",
    "REQUIRE_MAPPED_ROOT",
    "FAN_METRICS_MODE",
    "TEXTFILE_COLLECTOR_DIR",
    "NODE_DISKSTATS_DEVICE_EXCLUDE",
]

TARGETS = {
    "gpu-fast": "127.0.0.1:9836",
    "gpu-nvml": "127.0.0.1:9835",
    "smartctl": "127.0.0.1:9633",
    "cadvisor": "127.0.0.1:8080",
}


class ConfigError(RuntimeError):
    pass


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        if not VALID_KEY.fullmatch(key):
            raise ConfigError(f"{path}:{line_number}: invalid key {key!r}")
        if "\n" in value or "\r" in value:
            raise ConfigError(f"{path}:{line_number}: multiline values are not supported")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def boolean(value: str, key: str) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ConfigError(f"{key} must be true or false")


def defaults(existing: dict[str, str]) -> dict[str, str]:
    password = existing.get("GRAFANA_ADMIN_PASSWORD", "")
    if not password or password.startswith("REPLACE_"):
        password = secrets.token_hex(32)
    identity_salt = existing.get("GPU_IDENTITY_SALT", "")
    if not identity_salt or identity_salt.startswith("REPLACE_"):
        identity_salt = secrets.token_hex(16)
    return {
        **existing,
        "GRAFANA_ADMIN_PASSWORD": password,
        "OBSERVABILITY_UID": existing.get("OBSERVABILITY_UID", str(os.getuid())),
        "OBSERVABILITY_GID": existing.get("OBSERVABILITY_GID", str(os.getgid())),
        "HOST_LABEL": existing.get("HOST_LABEL", "localhost"),
        "PLATFORM_PROFILE": existing.get("PLATFORM_PROFILE", "generic"),
        "ENABLE_NVIDIA_GPU": existing.get("ENABLE_NVIDIA_GPU", "false"),
        "GPU_IDENTITY_MODE": existing.get("GPU_IDENTITY_MODE", "alias"),
        "GPU_IDENTITY_SALT": identity_salt,
        "ENABLE_SMART": existing.get("ENABLE_SMART", "false"),
        "SMART_DEVICE_HOST": existing.get("SMART_DEVICE_HOST", ""),
        "SMART_DEVICE_TYPE": existing.get("SMART_DEVICE_TYPE", "auto"),
        "PROTECTED_DEVICE_PATHS": existing.get("PROTECTED_DEVICE_PATHS", ""),
        "REQUIRE_MAPPED_ROOT": existing.get("REQUIRE_MAPPED_ROOT", "false"),
        "FAN_METRICS_MODE": existing.get("FAN_METRICS_MODE", "disabled"),
        "TEXTFILE_COLLECTOR_DIR": existing.get(
            "TEXTFILE_COLLECTOR_DIR", "./runtime/textfile_collector"
        ),
        "NODE_DISKSTATS_DEVICE_EXCLUDE": existing.get(
            "NODE_DISKSTATS_DEVICE_EXCLUDE", BASE_DISK_EXCLUDE
        ),
    }


def validate_scalar_config(config: dict[str, str]) -> None:
    label = config["HOST_LABEL"]
    if not VALID_LABEL.fullmatch(label):
        raise ConfigError("HOST_LABEL may contain only letters, digits, dot, underscore, and dash")
    if config["PLATFORM_PROFILE"] not in VALID_PROFILES:
        raise ConfigError(
            f"PLATFORM_PROFILE must be one of: {', '.join(sorted(VALID_PROFILES))}"
        )
    for key in ("OBSERVABILITY_UID", "OBSERVABILITY_GID"):
        if not config[key].isdigit():
            raise ConfigError(f"{key} must be a non-negative integer")
    boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU")
    if config["GPU_IDENTITY_MODE"] not in {"alias", "index", "uuid"}:
        raise ConfigError("GPU_IDENTITY_MODE must be alias, index, or uuid")
    if len(config["GPU_IDENTITY_SALT"]) < 16 or not re.fullmatch(
        r"[A-Za-z0-9_.-]+", config["GPU_IDENTITY_SALT"]
    ):
        raise ConfigError("GPU_IDENTITY_SALT must contain at least 16 safe characters")
    enable_smart = boolean(config["ENABLE_SMART"], "ENABLE_SMART")
    boolean(config["REQUIRE_MAPPED_ROOT"], "REQUIRE_MAPPED_ROOT")
    if enable_smart != bool(config["SMART_DEVICE_HOST"]):
        raise ConfigError("ENABLE_SMART and SMART_DEVICE_HOST must be configured together")
    if not re.fullmatch(r"[A-Za-z0-9,+_./-]+", config["SMART_DEVICE_TYPE"]):
        raise ConfigError("SMART_DEVICE_TYPE contains unsupported characters")
    if config["FAN_METRICS_MODE"] not in {"disabled", "textfile"}:
        raise ConfigError("FAN_METRICS_MODE must be disabled or textfile")
    if not config["TEXTFILE_COLLECTOR_DIR"]:
        raise ConfigError("TEXTFILE_COLLECTOR_DIR must not be empty")
    for key in ("SMART_DEVICE_HOST", "PROTECTED_DEVICE_PATHS", "TEXTFILE_COLLECTOR_DIR"):
        if any(character.isspace() for character in config[key]):
            raise ConfigError(f"{key} must not contain whitespace")
    if ":" in config["SMART_DEVICE_HOST"] or ":" in config["TEXTFILE_COLLECTOR_DIR"]:
        raise ConfigError("SMART_DEVICE_HOST and TEXTFILE_COLLECTOR_DIR must not contain colons")
    for key in CONFIG_ORDER:
        value = config[key]
        if any(character in value for character in "\n\r\0"):
            raise ConfigError(f"{key} contains an unsupported character")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require_block_device(path: str) -> str:
    resolved = os.path.realpath(path)
    try:
        mode = os.stat(resolved).st_mode
    except FileNotFoundError as error:
        raise ConfigError(f"device does not exist: {path}") from error
    if not stat.S_ISBLK(mode):
        raise ConfigError(f"not a block device: {path}")
    device_type = run(["lsblk", "-dn", "-o", "TYPE", resolved]).stdout.strip()
    if device_type != "disk":
        raise ConfigError(f"expected a whole-disk device, got {device_type or 'unknown'}: {path}")
    return resolved


def stable_device_path(path: str, allow_kernel_name: bool = False) -> str:
    resolved = require_block_device(path)
    supplied = Path(path)
    if str(supplied).startswith("/dev/disk/by-id/"):
        return str(supplied)

    candidates: list[Path] = []
    by_id = Path("/dev/disk/by-id")
    if by_id.is_dir():
        for candidate in by_id.iterdir():
            if "-part" in candidate.name:
                continue
            try:
                if os.path.realpath(candidate) == resolved:
                    candidates.append(candidate)
            except OSError:
                continue

    def preference(candidate: Path) -> tuple[int, str]:
        name = candidate.name
        if name.startswith("nvme-eui."):
            return (0, name)
        if name.startswith("nvme-uuid."):
            return (1, name)
        return (2, name)

    if candidates:
        return str(sorted(candidates, key=preference)[0])
    if allow_kernel_name:
        return resolved
    raise ConfigError(
        f"no stable /dev/disk/by-id path found for {path}; use --allow-kernel-device-names only after review"
    )


def default_smart_device_type(path: str) -> str:
    return "nvme" if Path(os.path.realpath(path)).name.startswith("nvme") else "auto"


def protected_devices(config: dict[str, str]) -> list[str]:
    return [item for item in config["PROTECTED_DEVICE_PATHS"].split(":") if item]


def build_disk_exclude(paths: list[str]) -> str:
    names = sorted({Path(os.path.realpath(path)).name for path in paths})
    if not names:
        return BASE_DISK_EXCLUDE
    escaped = "|".join(re.escape(name) for name in names)
    return rf"{BASE_DISK_EXCLUDE}|^({escaped})(p?[0-9]+)?$"


def protected_metric_regex(paths: list[str]) -> str:
    names = sorted({Path(os.path.realpath(path)).name for path in paths})
    if not names:
        return "a^"
    escaped = "|".join(re.escape(name) for name in names)
    return rf"^({escaped})(p?[0-9]+)?$"


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (PROJECT / path).resolve()


def atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_env(config: dict[str, str]) -> None:
    validate_scalar_config(config)
    ordered = CONFIG_ORDER + sorted(set(config) - set(CONFIG_ORDER))
    lines = [
        "# Generated by scripts/configure-host. Edit by rerunning that command.",
        "# This file contains a secret and persistent host identifiers; never commit it.",
    ]
    for key in ordered:
        lines.append(f"{key}={config[key]}")
    atomic_write(ENV_FILE, "\n".join(lines) + "\n", 0o600)


def render_prometheus(config: dict[str, str]) -> None:
    template = PROM_TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("@HOST_LABEL@", config["HOST_LABEL"]).replace(
        "@PROTECTED_DEVICE_REGEX@", protected_metric_regex(protected_devices(config))
    )
    if re.search(r"@[A-Z][A-Z0-9_]+@", rendered):
        raise ConfigError("Prometheus template contains an unresolved placeholder")
    atomic_write(PROM_RUNTIME / "prometheus.yml", rendered, 0o644)


def write_target(name: str, enabled: bool) -> None:
    content: list[dict[str, list[str]]] = []
    if enabled:
        content.append({"targets": [TARGETS[name]]})
    atomic_write(FILE_SD / f"{name}.json", json.dumps(content, separators=(",", ":")) + "\n", 0o644)


def write_targets(config: dict[str, str], mode: str) -> None:
    nvidia = boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU")
    smart = boolean(config["ENABLE_SMART"], "ENABLE_SMART")
    if mode == "normal":
        write_target("gpu-fast", nvidia)
        write_target("gpu-nvml", nvidia)
        write_target("smartctl", smart)
        if not (FILE_SD / "cadvisor.json").exists():
            write_target("cadvisor", False)
    elif mode == "benchmark":
        write_target("gpu-fast", nvidia)
        write_target("gpu-nvml", False)
        write_target("smartctl", False)
        write_target("cadvisor", False)
    elif mode == "off":
        for name in TARGETS:
            write_target(name, False)
    elif mode == "cadvisor-on":
        write_target("cadvisor", True)
    elif mode == "cadvisor-off":
        write_target("cadvisor", False)
    else:
        raise ConfigError(f"unsupported target mode: {mode}")


def prepare_runtime(config: dict[str, str], target_mode: str = "normal") -> None:
    PROM_RUNTIME.mkdir(parents=True, exist_ok=True)
    FILE_SD.mkdir(parents=True, exist_ok=True)
    LOCAL_TEXTFILE.mkdir(parents=True, exist_ok=True)
    textfile_dir = resolve_project_path(config["TEXTFILE_COLLECTOR_DIR"])
    if config["FAN_METRICS_MODE"] == "disabled":
        textfile_dir.mkdir(parents=True, exist_ok=True)
    elif not textfile_dir.is_dir():
        raise ConfigError(f"fan textfile directory does not exist: {textfile_dir}")
    render_prometheus(config)
    write_targets(config, target_mode)


def env_content(config: dict[str, str], show_sensitive: bool) -> str:
    rows = []
    for key in CONFIG_ORDER:
        value = config[key]
        if key in {"GRAFANA_ADMIN_PASSWORD", "GPU_IDENTITY_SALT"}:
            value = "<redacted>"
        elif not show_sensitive and key in {"SMART_DEVICE_HOST", "PROTECTED_DEVICE_PATHS"} and value:
            value = "<configured>"
        rows.append(f"{key}={value}")
    return "\n".join(rows)


def ask(prompt: str, current: str) -> str:
    answer = input(f"{prompt} [{current}]: ").strip()
    return answer or current


def ask_bool(prompt: str, current: bool) -> bool:
    marker = "Y/n" if current else "y/N"
    answer = input(f"{prompt} [{marker}]: ").strip().lower()
    if not answer:
        return current
    if answer in {"y", "yes"}:
        return True
    if answer in {"n", "no"}:
        return False
    raise ConfigError(f"invalid yes/no response: {answer}")


def configure(args: argparse.Namespace) -> int:
    existing = read_env()
    config = defaults(existing)
    if args.smart_device_type and not args.smart_device:
        raise ConfigError("--smart-device-type requires --smart-device")

    if args.interactive:
        if not sys.stdin.isatty():
            raise ConfigError("--interactive requires a terminal")
        config["HOST_LABEL"] = ask("Prometheus host label", config["HOST_LABEL"])
        config["PLATFORM_PROFILE"] = ask(
            "Platform profile (generic or supermicro-x11spa-tf)", config["PLATFORM_PROFILE"]
        )
        detected_nvidia = shutil.which("nvidia-smi") is not None
        enabled = boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU") or detected_nvidia
        config["ENABLE_NVIDIA_GPU"] = str(ask_bool("Enable NVIDIA collectors", enabled)).lower()
        config["GPU_IDENTITY_MODE"] = ask(
            "GPU identity mode (alias, index, or uuid)", config["GPU_IDENTITY_MODE"]
        )
        smart = input("SMART whole-disk path (blank disables SMART): ").strip()
        if smart:
            args.smart_device = smart
        else:
            args.disable_smart = True
        protected = input("Protected whole-disk paths, colon-separated (blank for none): ").strip()
        args.clear_protected_devices = not bool(protected)
        args.protected_device = protected.split(":") if protected else []
        config["REQUIRE_MAPPED_ROOT"] = str(
            ask_bool(
                "Require root filesystem source under /dev/mapper",
                boolean(config["REQUIRE_MAPPED_ROOT"], "REQUIRE_MAPPED_ROOT"),
            )
        ).lower()
        fan_dir = input("Fan textfile directory (blank disables fan metrics): ").strip()
        if fan_dir:
            args.fan_textfile_dir = fan_dir
        else:
            args.disable_fan_metrics = True

    if args.host_label is not None:
        config["HOST_LABEL"] = args.host_label
    if args.platform_profile is not None:
        config["PLATFORM_PROFILE"] = args.platform_profile
    if args.enable_nvidia:
        config["ENABLE_NVIDIA_GPU"] = "true"
    if args.disable_nvidia:
        config["ENABLE_NVIDIA_GPU"] = "false"
    if args.gpu_identity_mode:
        config["GPU_IDENTITY_MODE"] = args.gpu_identity_mode
    if args.smart_device:
        config["ENABLE_SMART"] = "true"
        config["SMART_DEVICE_HOST"] = stable_device_path(
            args.smart_device, args.allow_kernel_device_names
        )
        config["SMART_DEVICE_TYPE"] = args.smart_device_type or default_smart_device_type(
            config["SMART_DEVICE_HOST"]
        )
    if args.disable_smart:
        config["ENABLE_SMART"] = "false"
        config["SMART_DEVICE_HOST"] = ""
        config["SMART_DEVICE_TYPE"] = "auto"
    if args.protected_device and args.clear_protected_devices:
        raise ConfigError("use either --protected-device or --clear-protected-devices")
    if args.protected_device:
        selected = [
            stable_device_path(path, args.allow_kernel_device_names)
            for path in args.protected_device
        ]
        config["PROTECTED_DEVICE_PATHS"] = ":".join(selected)
    elif args.clear_protected_devices:
        config["PROTECTED_DEVICE_PATHS"] = ""
    if args.require_mapped_root:
        config["REQUIRE_MAPPED_ROOT"] = "true"
    if args.allow_any_root:
        config["REQUIRE_MAPPED_ROOT"] = "false"
    if args.fan_textfile_dir:
        config["FAN_METRICS_MODE"] = "textfile"
        config["TEXTFILE_COLLECTOR_DIR"] = args.fan_textfile_dir
    if args.disable_fan_metrics:
        config["FAN_METRICS_MODE"] = "disabled"
        config["TEXTFILE_COLLECTOR_DIR"] = "./runtime/textfile_collector"

    config["NODE_DISKSTATS_DEVICE_EXCLUDE"] = build_disk_exclude(protected_devices(config))
    validate_scalar_config(config)
    if config["SMART_DEVICE_HOST"] and os.path.realpath(config["SMART_DEVICE_HOST"]) in {
        os.path.realpath(path) for path in protected_devices(config)
    }:
        raise ConfigError("a SMART device cannot also be configured as protected")

    if not args.apply:
        print(env_content(config, args.show_sensitive))
        print("\nPreview only. Rerun with --apply to write the private host profile.")
        return 0

    write_env(config)
    prepare_runtime(config)
    if not args.quiet:
        print(f"Configured host profile {config['HOST_LABEL']!r} with mode 0600.")
        print(
            "Features: "
            f"nvidia={config['ENABLE_NVIDIA_GPU']}, smart={config['ENABLE_SMART']}, "
            f"fan_metrics={config['FAN_METRICS_MODE']}, "
            f"protected_devices={len(protected_devices(config))}."
        )
        print("Run scripts/doctor before starting the stack.")
    return 0


def lsblk_tree(path: str) -> dict[str, object]:
    result = run(["lsblk", "--json", "--paths", "-o", "NAME,TYPE,RO,MOUNTPOINTS", path])
    payload = json.loads(result.stdout)
    devices = payload.get("blockdevices", [])
    if not devices:
        raise ConfigError(f"lsblk returned no information for {path}")
    return devices[0]


def descendants(node: dict[str, object]) -> list[dict[str, object]]:
    result = [node]
    for child in node.get("children", []) or []:
        result.extend(descendants(child))
    return result


def check_config(quiet: bool = False, compose: bool = True) -> int:
    if not ENV_FILE.exists():
        raise ConfigError(".env is missing; run scripts/configure-host first")
    if stat.S_IMODE(ENV_FILE.stat().st_mode) != 0o600:
        raise ConfigError(".env must have mode 0600")
    config = defaults(read_env())
    validate_scalar_config(config)

    expected = PROM_TEMPLATE.read_text(encoding="utf-8").replace(
        "@HOST_LABEL@", config["HOST_LABEL"]
    ).replace("@PROTECTED_DEVICE_REGEX@", protected_metric_regex(protected_devices(config)))
    rendered = PROM_RUNTIME / "prometheus.yml"
    if not rendered.exists() or rendered.read_text(encoding="utf-8") != expected:
        raise ConfigError("generated Prometheus configuration is missing or stale; rerun configure-host")

    if config["PLATFORM_PROFILE"] == "supermicro-x11spa-tf":
        board_file = Path("/sys/class/dmi/id/board_name")
        board = board_file.read_text(encoding="utf-8").strip() if board_file.exists() else ""
        if "X11SPA-TF" not in board.upper():
            raise ConfigError(
                f"platform profile expects X11SPA-TF, detected {board or 'unknown board'}"
            )

    protected_real: set[str] = set()
    for device in protected_devices(config):
        resolved = require_block_device(device)
        protected_real.add(resolved)
        tree = lsblk_tree(resolved)
        if int(tree.get("ro", 0)) != 1:
            raise ConfigError(f"protected device is not read-only: {device}")
        mounted = [
            str(item["name"])
            for item in descendants(tree)
            if any(item.get("mountpoints", []) or [])
        ]
        if mounted:
            raise ConfigError(f"protected device has mounted descendants: {device}")

    if boolean(config["ENABLE_SMART"], "ENABLE_SMART"):
        smart = require_block_device(config["SMART_DEVICE_HOST"])
        if smart in protected_real:
            raise ConfigError("SMART_DEVICE_HOST must not also be a protected device")

    if boolean(config["REQUIRE_MAPPED_ROOT"], "REQUIRE_MAPPED_ROOT"):
        root_source = run(["findmnt", "-n", "-o", "SOURCE", "/"]).stdout.strip()
        if not root_source.startswith("/dev/mapper/"):
            raise ConfigError(f"root source is not under /dev/mapper: {root_source}")

    if boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU"):
        result = run(
            ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"], check=False
        )
        count = len([line for line in result.stdout.splitlines() if line.strip()])
        if result.returncode != 0 or count < 1:
            raise ConfigError("NVIDIA collection is enabled but nvidia-smi found no GPUs")

    textfile_dir = resolve_project_path(config["TEXTFILE_COLLECTOR_DIR"])
    if not textfile_dir.is_dir():
        raise ConfigError(f"textfile collector directory does not exist: {textfile_dir}")
    if not os.access(textfile_dir, os.R_OK | os.X_OK):
        raise ConfigError(f"textfile collector directory is not readable: {textfile_dir}")

    if compose:
        result = run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(PROJECT),
                "--file",
                str(PROJECT / "compose.yaml"),
                "config",
                "--quiet",
            ],
            check=False,
        )
        if result.returncode != 0:
            raise ConfigError(f"Docker Compose validation failed: {result.stderr.strip()}")

    if not quiet:
        print(
            f"Host profile is valid: label={config['HOST_LABEL']}, "
            f"platform={config['PLATFORM_PROFILE']}, "
            f"nvidia={config['ENABLE_NVIDIA_GPU']}, smart={config['ENABLE_SMART']}, "
            f"fan_metrics={config['FAN_METRICS_MODE']}, "
            f"protected_devices={len(protected_devices(config))}."
        )
    return 0


def services(config: dict[str, str], mode: str) -> list[str]:
    if mode == "normal":
        selected = ["node-exporter", "prometheus", "grafana"]
        if boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU"):
            selected.extend(["fast-gpu-exporter", "nvml-exporter"])
        if boolean(config["ENABLE_SMART"], "ENABLE_SMART"):
            selected.append("smartctl-exporter")
        return selected
    if mode == "benchmark":
        selected = ["node-exporter", "prometheus"]
        if boolean(config["ENABLE_NVIDIA_GPU"], "ENABLE_NVIDIA_GPU"):
            selected.append("fast-gpu-exporter")
        return selected
    raise ConfigError(f"unsupported service mode: {mode}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    configure_parser = commands.add_parser("configure")
    configure_parser.add_argument("--apply", action="store_true")
    configure_parser.add_argument("--quiet", action="store_true")
    configure_parser.add_argument("--interactive", action="store_true")
    configure_parser.add_argument("--non-interactive", action="store_true")
    configure_parser.add_argument("--show-sensitive", action="store_true")
    configure_parser.add_argument("--host-label")
    configure_parser.add_argument("--platform-profile", choices=sorted(VALID_PROFILES))
    nvidia = configure_parser.add_mutually_exclusive_group()
    nvidia.add_argument("--enable-nvidia", action="store_true")
    nvidia.add_argument("--disable-nvidia", action="store_true")
    configure_parser.add_argument(
        "--gpu-identity-mode", choices=["alias", "index", "uuid"]
    )
    smart = configure_parser.add_mutually_exclusive_group()
    smart.add_argument("--smart-device")
    smart.add_argument("--disable-smart", action="store_true")
    configure_parser.add_argument("--smart-device-type")
    configure_parser.add_argument("--protected-device", action="append", default=[])
    configure_parser.add_argument("--clear-protected-devices", action="store_true")
    root_policy = configure_parser.add_mutually_exclusive_group()
    root_policy.add_argument("--require-mapped-root", action="store_true")
    root_policy.add_argument("--allow-any-root", action="store_true")
    fan = configure_parser.add_mutually_exclusive_group()
    fan.add_argument("--fan-textfile-dir")
    fan.add_argument("--disable-fan-metrics", action="store_true")
    configure_parser.add_argument("--allow-kernel-device-names", action="store_true")

    check_parser = commands.add_parser("check")
    check_parser.add_argument("--quiet", action="store_true")
    check_parser.add_argument("--no-compose", action="store_true")

    targets_parser = commands.add_parser("targets")
    targets_parser.add_argument(
        "mode", choices=["normal", "benchmark", "off", "cadvisor-on", "cadvisor-off"]
    )

    services_parser = commands.add_parser("services")
    services_parser.add_argument("mode", choices=["normal", "benchmark"])
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "configure":
            if args.interactive and args.non_interactive:
                raise ConfigError("use either --interactive or --non-interactive")
            if not args.interactive and not args.non_interactive:
                raise ConfigError("choose --interactive or --non-interactive")
            return configure(args)
        config = defaults(read_env())
        validate_scalar_config(config)
        if args.command == "check":
            return check_config(args.quiet, not args.no_compose)
        if args.command == "targets":
            write_targets(config, args.mode)
            return 0
        if args.command == "services":
            print("\n".join(services(config, args.mode)))
            return 0
    except (ConfigError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
