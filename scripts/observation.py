#!/usr/bin/env python3
"""Bounded, privacy-preserving Prometheus observation and STDIO MCP support."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import statistics
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "observation-v1"
VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
PROMETHEUS_URL = "http://127.0.0.1:9090"
MAX_WINDOW_SECONDS = 24 * 60 * 60
MAX_QUERY_POINTS = 600
MAX_RETURNED_POINTS = 120
MAX_TOTAL_RETURNED_POINTS = 10_000
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3
EXIT_DATA = 4
EXIT_OUTPUT = 5
PROFILES = ("system", "gpu", "thermal", "health", "benchmark")
MCP_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2026-07-28")
SAFE_JOBS = {"prometheus", "node-fast", "node-slow", "gpu-fast", "gpu-nvml", "smartctl", "cadvisor"}
SAFE_THROTTLE_REASONS = {
    "gpu_idle", "applications_clocks", "software_power_cap", "hardware_slowdown",
    "hardware_thermal", "hardware_power_brake", "software_thermal", "sync_boost",
}
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
META_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")
META_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")


class ObservationError(RuntimeError):
    def __init__(self, code: str, message: str, exit_code: int = EXIT_DATA, remediation: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.remediation = remediation


class UsageError(ObservationError):
    def __init__(self, message: str):
        super().__init__("usage", message, EXIT_USAGE)


class PrometheusUnavailable(ObservationError):
    def __init__(self, message: str = "Prometheus is unavailable on loopback"):
        super().__init__(
            "monitoring_unavailable", message, EXIT_UNAVAILABLE,
            "Ask a human operator to start or repair monitoring; this interface never controls lifecycle.",
        )


@dataclass(frozen=True)
class MetricSpec:
    id: str
    profile: str
    unit: str
    query: str
    dimensions: tuple[str, ...] = ()
    feature: str = "core"
    stale_after: int = 45


def _spec(id: str, profile: str, unit: str, query: str, dimensions: tuple[str, ...] = (), feature: str = "core", stale_after: int = 45) -> MetricSpec:
    return MetricSpec(id, profile, unit, query, dimensions, feature, stale_after)


METRICS: tuple[MetricSpec, ...] = (
    _spec("system.cpu.utilization", "system", "percent", '100 - avg(rate(node_cpu_seconds_total{job="node-fast",mode="idle"}[30s])) * 100'),
    _spec("system.memory.used", "system", "bytes", 'sum(node_memory_MemTotal_bytes{job="node-fast"}) - sum(node_memory_MemAvailable_bytes{job="node-fast"})'),
    _spec("system.memory.available", "system", "bytes", 'sum(node_memory_MemAvailable_bytes{job="node-fast"})'),
    _spec("system.pressure.cpu", "system", "ratio", 'sum(rate(node_pressure_cpu_waiting_seconds_total{job="node-fast"}[30s]))'),
    _spec("system.pressure.memory", "system", "ratio", 'sum(rate(node_pressure_memory_waiting_seconds_total{job="node-fast"}[30s]))'),
    _spec("system.pressure.io", "system", "ratio", 'sum(rate(node_pressure_io_waiting_seconds_total{job="node-fast"}[30s]))'),
    _spec("system.disk.read", "system", "bytes_per_second", 'sum(rate(node_disk_read_bytes_total{job="node-fast"}[30s]))'),
    _spec("system.disk.write", "system", "bytes_per_second", 'sum(rate(node_disk_written_bytes_total{job="node-fast"}[30s]))'),
    _spec("system.network.receive", "system", "bytes_per_second", 'sum(rate(node_network_receive_bytes_total{job="node-fast",device!="lo"}[30s]))'),
    _spec("system.network.transmit", "system", "bytes_per_second", 'sum(rate(node_network_transmit_bytes_total{job="node-fast",device!="lo"}[30s]))'),
    _spec("system.oom_kills", "system", "events_per_second", 'sum(rate(node_vmstat_oom_kill{job="node-fast"}[5m]))'),
    _spec("gpu.sampler.up", "gpu", "boolean", "supermicro_gpu_sampler_up", feature="nvidia", stale_after=5),
    _spec("gpu.sample.age", "gpu", "seconds", "supermicro_gpu_sample_age_seconds", feature="nvidia", stale_after=5),
    _spec("gpu.utilization", "gpu", "percent", "supermicro_gpu_utilization_percent", ("gpu",), "nvidia", 5),
    _spec("gpu.utilization_1s.min", "gpu", "percent", "supermicro_gpu_utilization_1s_percent_min", ("gpu",), "nvidia", 5),
    _spec("gpu.utilization_1s.mean", "gpu", "percent", "supermicro_gpu_utilization_1s_percent_average", ("gpu",), "nvidia", 5),
    _spec("gpu.utilization_1s.max", "gpu", "percent", "supermicro_gpu_utilization_1s_percent_max", ("gpu",), "nvidia", 5),
    _spec("gpu.memory.utilization", "gpu", "percent", "supermicro_gpu_memory_utilization_percent", ("gpu",), "nvidia", 5),
    _spec("gpu.memory.used", "gpu", "bytes", "supermicro_gpu_memory_used_bytes", ("gpu",), "nvidia", 5),
    _spec("gpu.memory.total", "gpu", "bytes", "supermicro_gpu_memory_total_bytes", ("gpu",), "nvidia", 5),
    _spec("gpu.power", "gpu", "watts", "supermicro_gpu_power_draw_watts", ("gpu",), "nvidia", 5),
    _spec("gpu.temperature", "gpu", "celsius", "supermicro_gpu_temperature_celsius", ("gpu",), "nvidia", 5),
    _spec("gpu.clock.graphics", "gpu", "hertz", "supermicro_gpu_graphics_clock_hertz", ("gpu",), "nvidia", 5),
    _spec("gpu.clock.memory", "gpu", "hertz", "supermicro_gpu_memory_clock_hertz", ("gpu",), "nvidia", 5),
    _spec("gpu.performance_state", "gpu", "state", "supermicro_gpu_performance_state", ("gpu",), "nvidia", 5),
    _spec("gpu.pcie.generation", "gpu", "generation", "supermicro_gpu_pcie_link_generation", ("gpu",), "nvidia", 5),
    _spec("gpu.pcie.width", "gpu", "lanes", "supermicro_gpu_pcie_link_width", ("gpu",), "nvidia", 5),
    _spec("gpu.throttle.mask", "gpu", "bitmask", "supermicro_gpu_throttle_reasons_mask", ("gpu",), "nvidia", 5),
    _spec("gpu.throttle.active", "gpu", "boolean", "supermicro_gpu_throttle_reason_active", ("gpu", "reason"), "nvidia", 5),
    _spec("thermal.temperature.hwmon.max", "thermal", "celsius", 'max(node_hwmon_temp_celsius{job="node-slow"})', stale_after=45),
    _spec("thermal.temperature.zone.max", "thermal", "celsius", 'max(node_thermal_zone_temp{job="node-slow"})', stale_after=45),
    _spec("thermal.fan.controller_active", "thermal", "boolean", "supermicro_fan_controller_active", feature="fan", stale_after=120),
    _spec("thermal.fan.failsafe", "thermal", "boolean", "supermicro_fan_controller_failsafe", feature="fan", stale_after=120),
    _spec("thermal.fan.sample_healthy", "thermal", "boolean", "supermicro_fan_sensor_read_healthy", feature="fan", stale_after=120),
    _spec("thermal.fan.sample_age", "thermal", "seconds", "time() - supermicro_fan_sample_timestamp_seconds", feature="fan", stale_after=120),
    _spec("thermal.fan.speed.max", "thermal", "rpm", "max(supermicro_fan_speed_rpm)", feature="fan", stale_after=120),
    _spec("thermal.fan.duty.max", "thermal", "percent", "max(supermicro_fan_zone_duty_percent)", feature="fan", stale_after=120),
    _spec("thermal.fan.temperature.max", "thermal", "celsius", "max(supermicro_fan_temperature_celsius)", feature="fan", stale_after=120),
    _spec("health.target.up", "health", "boolean", 'min by (job) (up{job=~"prometheus|node-fast|node-slow|gpu-fast|gpu-nvml|smartctl|cadvisor"})', ("job",)),
    _spec("health.scrape.duration", "health", "seconds", 'max by (job) (scrape_duration_seconds{job=~"prometheus|node-fast|node-slow|gpu-fast|gpu-nvml|smartctl|cadvisor"})', ("job",)),
    _spec("health.prometheus.head_series", "health", "series", "prometheus_tsdb_head_series"),
    _spec("health.prometheus.storage", "health", "bytes", "sum(prometheus_tsdb_storage_blocks_bytes)"),
    _spec("health.smart.passed", "health", "boolean", "min(smartctl_device_smart_status)", feature="smart", stale_after=600),
)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def rfc3339(value: dt.datetime) -> str:
    value = value.astimezone(dt.timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str) -> dt.datetime:
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as error:
        raise UsageError(f"invalid RFC 3339 timestamp: {value}") from error
    if parsed.tzinfo is None:
        raise UsageError("timestamps must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def parse_duration(value: str) -> dt.timedelta:
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h)", value.strip())
    if not match:
        raise UsageError("duration must be a positive integer followed by s, m, or h")
    multiplier = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    seconds = int(match.group(1)) * multiplier
    if seconds > MAX_WINDOW_SECONDS:
        raise UsageError("observation windows may not exceed 24 hours")
    return dt.timedelta(seconds=seconds)


def resolve_window(since: str, until: str | None = None, now: dt.datetime | None = None) -> tuple[dt.datetime, dt.datetime]:
    end = parse_timestamp(until) if until else (now or utc_now())
    try:
        delta = parse_duration(since)
        start = end - delta
    except UsageError:
        start = parse_timestamp(since)
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        raise UsageError("window start must precede window end")
    if seconds > MAX_WINDOW_SECONDS:
        raise UsageError("observation windows may not exceed 24 hours")
    return start, end


def nearest_rank_p95(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of no values")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def finite_number(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ObservationError("invalid_data", "Prometheus returned a non-numeric sample") from error
    if not math.isfinite(value):
        raise ObservationError("invalid_data", "Prometheus returned a non-finite sample")
    return value


def json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ObservationError("invalid_data", "result cannot be represented as finite JSON") from error


def strict_json_loads(value: bytes | str) -> Any:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-finite JSON constant: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value.strip().strip("'\"")
    return values


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def config() -> dict[str, str]:
    path = Path(os.environ.get("OBSERVABILITY_CONFIG_FILE", project_root() / ".env"))
    return read_env(path)


def enabled_features(values: dict[str, str]) -> dict[str, bool]:
    return {
        "core": True,
        "nvidia": values.get("ENABLE_NVIDIA_GPU", "false").lower() == "true",
        "smart": values.get("ENABLE_SMART", "false").lower() == "true",
        "fan": values.get("FAN_METRICS_MODE", "disabled") == "textfile",
    }


def profile_specs(profile: str) -> list[MetricSpec]:
    if profile not in PROFILES:
        raise UsageError(f"profile must be one of: {', '.join(PROFILES)}")
    selected = {"system", "gpu", "thermal", "health"} if profile == "benchmark" else {profile}
    return [spec for spec in METRICS if spec.profile in selected]


def envelope(command: str, profile: str | None, status: str = "ok", *, now: dt.datetime | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "generated_at": rfc3339(now or utc_now()),
        "status": status,
        "source": {"type": "prometheus", "endpoint": "http://127.0.0.1:9090"},
        "metrics": [],
        "warnings": [],
    }
    if profile:
        result["profile"] = profile
    return result


def error_envelope(command: str, profile: str | None, error: ObservationError) -> dict[str, Any]:
    result = envelope(command, profile, "unavailable" if error.exit_code == EXIT_UNAVAILABLE else "error")
    detail: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.remediation:
        detail["remediation"] = error.remediation
    result["error"] = detail
    return result


class PrometheusClient:
    def __init__(self, base_url: str = PROMETHEUS_URL, timeout: float = 2.0):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
            raise ValueError("Prometheus endpoint must be an explicit 127.0.0.1 HTTP port")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, params: dict[str, str] | None = None, *, expect_json: bool = True) -> Any:
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"supermicro-observability/{VERSION}"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(4 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise PrometheusUnavailable() from error
        if len(body) > 4 * 1024 * 1024:
            raise ObservationError("response_too_large", "Prometheus response exceeded 4 MiB")
        if not expect_json:
            return body
        try:
            payload = strict_json_loads(body)
        except (UnicodeDecodeError, ValueError) as error:
            raise ObservationError("malformed_response", "Prometheus returned malformed JSON") from error
        if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            message = payload.get("error", "Prometheus query failed") if isinstance(payload, dict) else "Prometheus query failed"
            raise ObservationError("query_failed", str(message)[:256])
        return payload["data"]

    def ready(self) -> None:
        self._request("/-/ready", expect_json=False)

    def instant(self, query: str, when: dt.datetime | None = None) -> list[dict[str, Any]]:
        params = {"query": query}
        if when:
            params["time"] = rfc3339(when)
        data = self._request("/api/v1/query", params)
        if data.get("resultType") not in {"vector", "scalar"} or not isinstance(data.get("result"), list):
            raise ObservationError("malformed_response", "Prometheus returned an unexpected instant result")
        return data["result"]

    def range(self, query: str, start: dt.datetime, end: dt.datetime, step: int) -> list[dict[str, Any]]:
        data = self._request("/api/v1/query_range", {
            "query": query, "start": rfc3339(start), "end": rfc3339(end), "step": str(step),
        })
        if data.get("resultType") != "matrix" or not isinstance(data.get("result"), list):
            raise ObservationError("malformed_response", "Prometheus returned an unexpected range result")
        return data["result"]


def gpu_alias(raw: str, salt: str) -> str:
    digest = hmac.new(salt.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    return f"gpu-{digest}"


def safe_dimensions(labels: Any, spec: MetricSpec, salt: str | None) -> tuple[dict[str, str], list[str]]:
    if not isinstance(labels, dict):
        raise ObservationError("malformed_response", "Prometheus returned malformed labels")
    dimensions: dict[str, str] = {}
    warnings: list[str] = []
    if "gpu" in spec.dimensions:
        raw = labels.get("gpu_id")
        if isinstance(raw, str) and raw:
            if salt:
                dimensions["gpu"] = gpu_alias(raw, salt)
            else:
                warnings.append("GPU dimensions were suppressed because the private alias salt was unavailable.")
    if "reason" in spec.dimensions and labels.get("reason") in SAFE_THROTTLE_REASONS:
        dimensions["reason"] = labels["reason"]
    if "job" in spec.dimensions and labels.get("job") in SAFE_JOBS:
        dimensions["job"] = labels["job"]
    return dimensions, warnings


def _disabled_record(spec: MetricSpec) -> dict[str, Any]:
    return {"id": spec.id, "unit": spec.unit, "dimensions": {}, "availability": "disabled"}


def _merge_status(result: dict[str, Any], availability: str) -> None:
    if availability in {"missing", "stale", "error"} and result["status"] == "ok":
        result["status"] = "partial"


def _value_pairs(item: dict[str, Any], key: str) -> list[tuple[float, float]]:
    if not isinstance(item, dict):
        raise ObservationError("malformed_response", "Prometheus result item was malformed")
    raw_values = item.get(key)
    if key == "value":
        raw_values = [raw_values]
    if not isinstance(raw_values, list):
        raise ObservationError("malformed_response", "Prometheus sample data was malformed")
    pairs: list[tuple[float, float]] = []
    for pair in raw_values:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ObservationError("malformed_response", "Prometheus sample pair was malformed")
        pairs.append((finite_number(pair[0]), finite_number(pair[1])))
    return pairs


def snapshot(profile: str = "benchmark", *, client: PrometheusClient | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    client = client or PrometheusClient()
    generated = now or utc_now()
    result = envelope("snapshot", profile, now=generated)
    values = config()
    features = enabled_features(values)
    raw_salt = values.get("GPU_IDENTITY_SALT", "")
    salt = raw_salt if len(raw_salt) >= 16 and re.fullmatch(r"[A-Za-z0-9_.-]+", raw_salt) else None
    try:
        client.ready()
    except PrometheusUnavailable:
        raise
    for spec in profile_specs(profile):
        if not features[spec.feature]:
            result["metrics"].append(_disabled_record(spec))
            continue
        try:
            samples = client.instant(spec.query, generated)
            if len(samples) > 128:
                raise ObservationError("cardinality_limit", f"metric {spec.id} exceeded 128 series")
            if not samples:
                record = {"id": spec.id, "unit": spec.unit, "dimensions": {}, "availability": "missing"}
                result["metrics"].append(record)
                _merge_status(result, "missing")
                continue
            for item in samples:
                pairs = _value_pairs(item, "value")
                dimensions, warnings = safe_dimensions(item.get("metric", {}), spec, salt)
                result["warnings"].extend(warnings)
                timestamp, value = pairs[0]
                availability = "available" if generated.timestamp() - timestamp <= spec.stale_after else "stale"
                if spec.id in {"gpu.sample.age", "thermal.fan.sample_age"} and value > spec.stale_after:
                    availability = "stale"
                result["metrics"].append({"id": spec.id, "unit": spec.unit, "dimensions": dimensions, "availability": availability, "value": value})
                _merge_status(result, availability)
        except PrometheusUnavailable:
            raise
        except ObservationError:
            raise
    result["warnings"] = sorted(set(result["warnings"]))
    json_bytes(result)
    return result


def summarize(since: str, profile: str = "benchmark", *, until: str | None = None, include_series: bool = False, client: PrometheusClient | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    client = client or PrometheusClient()
    start, end = resolve_window(since, until, now)
    duration = (end - start).total_seconds()
    query_step = max(1, math.ceil(duration / (MAX_QUERY_POINTS - 1)))
    return_step = max(query_step, math.ceil(duration / (MAX_RETURNED_POINTS - 1)))
    result = envelope("summarize", profile, now=end)
    result["window"] = {"start": rfc3339(start), "end": rfc3339(end), "seconds": duration, "query_step_seconds": query_step}
    values = config()
    features = enabled_features(values)
    raw_salt = values.get("GPU_IDENTITY_SALT", "")
    salt = raw_salt if len(raw_salt) >= 16 and re.fullmatch(r"[A-Za-z0-9_.-]+", raw_salt) else None
    returned_total = 0
    client.ready()
    for spec in profile_specs(profile):
        if not features[spec.feature]:
            result["metrics"].append(_disabled_record(spec))
            continue
        try:
            series = client.range(spec.query, start, end, query_step)
            if len(series) > 128:
                raise ObservationError("cardinality_limit", f"metric {spec.id} exceeded 128 series")
            if not series:
                result["metrics"].append({"id": spec.id, "unit": spec.unit, "dimensions": {}, "availability": "missing"})
                _merge_status(result, "missing")
                continue
            for item in series:
                pairs = _value_pairs(item, "values")
                dimensions, warnings = safe_dimensions(item.get("metric", {}), spec, salt)
                result["warnings"].extend(warnings)
                numbers = [value for _, value in pairs]
                if not numbers:
                    availability = "missing"
                    record = {"id": spec.id, "unit": spec.unit, "dimensions": dimensions, "availability": availability}
                else:
                    expected = min(MAX_QUERY_POINTS, math.floor(duration / query_step) + 1)
                    coverage = min(1.0, len(numbers) / expected)
                    availability = "available" if coverage >= 0.8 else "partial"
                    record = {
                        "id": spec.id, "unit": spec.unit, "dimensions": dimensions, "availability": availability,
                        "summary": {"min": min(numbers), "mean": statistics.fmean(numbers), "p95": nearest_rank_p95(numbers), "max": max(numbers), "points": len(numbers), "coverage": coverage},
                    }
                    if include_series:
                        stride = max(1, math.ceil(return_step / query_step))
                        public_points = [{"at": rfc3339(dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)), "value": value} for timestamp, value in pairs[::stride]][:MAX_RETURNED_POINTS]
                        if returned_total + len(public_points) > MAX_TOTAL_RETURNED_POINTS:
                            raise ObservationError("point_limit", "included series exceeded 10,000 total points")
                        returned_total += len(public_points)
                        record["series"] = public_points
                result["metrics"].append(record)
                _merge_status(result, availability)
        except PrometheusUnavailable:
            raise
        except ObservationError:
            raise
    result["warnings"] = sorted(set(result["warnings"]))
    json_bytes(result)
    return result


def catalog(profile: str = "benchmark") -> dict[str, Any]:
    result = envelope("catalog", profile)
    features = enabled_features(config())
    result["metrics"] = [
        {"id": spec.id, "unit": spec.unit, "dimensions": {}, "dimension_keys": list(spec.dimensions), "availability": "enabled" if features[spec.feature] else "disabled"}
        for spec in profile_specs(profile)
    ]
    return result


def status(*, client: PrometheusClient | None = None) -> dict[str, Any]:
    client = client or PrometheusClient()
    result = envelope("status", None)
    try:
        client.ready()
    except PrometheusUnavailable as error:
        return error_envelope("status", None, error)
    values = config()
    features = enabled_features(values)
    result["metrics"] = [
        {"id": "monitoring.prometheus.ready", "unit": "boolean", "dimensions": {}, "availability": "available", "value": 1.0},
        *({"id": f"monitoring.feature.{name}", "unit": "boolean", "dimensions": {}, "availability": "available", "value": float(enabled)} for name, enabled in features.items() if name != "core"),
    ]
    return result


def validate_label(label: str) -> None:
    if not LABEL_RE.fullmatch(label):
        raise UsageError("label must be 1-64 safe characters: letters, digits, dot, underscore, or dash")


def parse_metadata(items: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise UsageError("metadata must use key=value")
        key, value = item.split("=", 1)
        if not META_KEY_RE.fullmatch(key) or not META_VALUE_RE.fullmatch(value):
            raise UsageError("metadata keys or values exceed the safe character/length bounds")
        if key in parsed:
            raise UsageError(f"duplicate metadata key: {key}")
        parsed[key] = value
    if len(parsed) > 16:
        raise UsageError("at most 16 metadata entries are allowed")
    return parsed


def encode_token(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json_bytes(payload)).decode("ascii").rstrip("=")
    checksum = hashlib.sha256(("supermicro-observability-session-v1." + body).encode("ascii")).hexdigest()[:24]
    return f"obs1.{body}.{checksum}"


def decode_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "obs1" or len(parts[1]) > 4096:
        raise UsageError("invalid session token")
    expected = hashlib.sha256(("supermicro-observability-session-v1." + parts[1]).encode("ascii")).hexdigest()[:24]
    if not secrets.compare_digest(parts[2], expected):
        raise UsageError("session token checksum failed")
    try:
        body = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        payload = strict_json_loads(body)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise UsageError("invalid session token payload") from error
    if not isinstance(payload, dict) or payload.get("v") != 1 or not isinstance(payload.get("started_at"), str) or not isinstance(payload.get("label"), str) or not isinstance(payload.get("metadata"), dict):
        raise UsageError("invalid session token fields")
    validate_label(payload["label"])
    parse_timestamp(payload["started_at"])
    parse_metadata([f"{key}={value}" for key, value in payload["metadata"].items()])
    return payload


def begin_session(label: str, metadata: Iterable[str] = (), *, client: PrometheusClient | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_label(label)
    parsed_metadata = parse_metadata(metadata)
    client = client or PrometheusClient()
    client.ready()
    started = now or utc_now()
    result = envelope("begin", None, now=started)
    result["session"] = {"token": encode_token({"v": 1, "started_at": rfc3339(started), "label": label, "metadata": parsed_metadata}), "label": label, "metadata": parsed_metadata, "started_at": rfc3339(started)}
    return result


def end_session(token: str, profile: str = "benchmark", *, include_series: bool = False, client: PrometheusClient | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    payload = decode_token(token)
    end = now or utc_now()
    report = summarize(payload["started_at"], profile, until=rfc3339(end), include_series=include_series, client=client)
    report["command"] = "end"
    report["session"] = {"label": payload["label"], "metadata": payload["metadata"], "started_at": payload["started_at"], "ended_at": rfc3339(end)}
    return report


def atomic_output(path: Path, value: dict[str, Any]) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ObservationError("output_exists", f"refusing to overwrite existing output: {path}", EXIT_OUTPUT)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(json_bytes(value) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(temporary, path)
            os.unlink(temporary)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    except ObservationError:
        raise
    except FileExistsError as error:
        raise ObservationError("output_exists", f"refusing to overwrite existing output: {path}", EXIT_OUTPUT) from error
    except OSError as error:
        raise ObservationError("output_failed", f"could not write output: {error}", EXIT_OUTPUT) from error


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JSONArgumentParser(prog="observe", description="Bounded local monitoring observation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true")
    catalog_parser = subparsers.add_parser("catalog")
    catalog_parser.add_argument("--profile", choices=PROFILES, default="benchmark")
    catalog_parser.add_argument("--json", action="store_true")
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--profile", choices=PROFILES, default="benchmark")
    snapshot_parser.add_argument("--json", action="store_true")
    summary_parser = subparsers.add_parser("summarize")
    summary_parser.add_argument("--since", required=True)
    summary_parser.add_argument("--until")
    summary_parser.add_argument("--profile", choices=PROFILES, default="benchmark")
    summary_parser.add_argument("--include-series", action="store_true")
    summary_parser.add_argument("--json", action="store_true")
    begin_parser = subparsers.add_parser("begin")
    begin_parser.add_argument("--label", required=True)
    begin_parser.add_argument("--metadata", action="append", default=[])
    begin_parser.add_argument("--json", action="store_true")
    end_parser = subparsers.add_parser("end")
    end_parser.add_argument("token")
    end_parser.add_argument("--profile", choices=PROFILES, default="benchmark")
    end_parser.add_argument("--include-series", action="store_true")
    end_parser.add_argument("--output", type=Path)
    end_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("mcp")
    return parser


def emit(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(json_bytes(value) + b"\n")
    sys.stdout.buffer.flush()


def cli_main(argv: list[str] | None = None) -> int:
    command = "unknown"
    profile: str | None = None
    try:
        args = build_parser().parse_args(argv)
        command = args.command
        profile = getattr(args, "profile", None)
        if command == "mcp":
            return mcp_main()
        if command == "status":
            result = status()
            emit(result)
            return EXIT_UNAVAILABLE if result["status"] == "unavailable" else 0
        if command == "catalog":
            result = catalog(profile)
        elif command == "snapshot":
            result = snapshot(profile)
        elif command == "summarize":
            result = summarize(args.since, profile, until=args.until, include_series=args.include_series)
        elif command == "begin":
            result = begin_session(args.label, args.metadata)
        elif command == "end":
            result = end_session(args.token, profile, include_series=args.include_series)
            if args.output:
                atomic_output(args.output, result)
        else:
            raise UsageError("unsupported command")
        emit(result)
        return 0
    except ObservationError as error:
        emit(error_envelope(command, profile, error))
        return error.exit_code
    except BrokenPipeError:
        return 0


TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"name": "observability_status", "description": "Check whether loopback Prometheus is ready; never starts monitoring.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "metric_catalog", "description": "List the bounded metric catalog and optional-feature availability.", "inputSchema": {"type": "object", "properties": {"profile": {"type": "string", "enum": list(PROFILES), "default": "benchmark"}}, "additionalProperties": False}},
    {"name": "snapshot", "description": "Read an allowlisted current metric snapshot.", "inputSchema": {"type": "object", "properties": {"profile": {"type": "string", "enum": list(PROFILES), "default": "benchmark"}}, "additionalProperties": False}},
    {"name": "summarize_window", "description": "Summarize at most 24 hours of allowlisted metrics.", "inputSchema": {"type": "object", "properties": {"since": {"type": "string"}, "until": {"type": "string"}, "profile": {"type": "string", "enum": list(PROFILES), "default": "benchmark"}, "include_series": {"type": "boolean", "default": False}}, "required": ["since"], "additionalProperties": False}},
    {"name": "begin_session", "description": "Check readiness and create a self-contained observation session token without writing files.", "inputSchema": {"type": "object", "properties": {"label": {"type": "string", "maxLength": 64}, "metadata": {"type": "object", "maxProperties": 16, "additionalProperties": {"type": "string", "maxLength": 128}}}, "required": ["label"], "additionalProperties": False}},
    {"name": "end_session", "description": "Summarize a bounded session represented by a begin_session token.", "inputSchema": {"type": "object", "properties": {"token": {"type": "string"}, "profile": {"type": "string", "enum": list(PROFILES), "default": "benchmark"}, "include_series": {"type": "boolean", "default": False}}, "required": ["token"], "additionalProperties": False}},
)


def annotated_tools() -> list[dict[str, Any]]:
    return [{**tool, "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": tool["name"] not in {"begin_session"}, "openWorldHint": False}} for tool in TOOL_DEFINITIONS]


def mcp_tool_call(name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise UsageError("tool arguments must be an object")
    allowed = next((tool for tool in TOOL_DEFINITIONS if tool["name"] == name), None)
    if allowed is None:
        raise UsageError(f"unknown tool: {name}")
    schema = allowed["inputSchema"]
    unknown = set(arguments) - set(schema.get("properties", {}))
    missing = set(schema.get("required", [])) - set(arguments)
    if unknown or missing:
        raise UsageError("tool arguments contain unknown fields or omit required fields")
    profile = arguments.get("profile", "benchmark")
    if profile not in PROFILES:
        raise UsageError("invalid profile")
    if name == "observability_status":
        return status()
    if name == "metric_catalog":
        return catalog(profile)
    if name == "snapshot":
        return snapshot(profile)
    if name == "summarize_window":
        if not isinstance(arguments.get("since"), str) or ("until" in arguments and not isinstance(arguments["until"], str)) or not isinstance(arguments.get("include_series", False), bool):
            raise UsageError("invalid summarize_window arguments")
        return summarize(arguments["since"], profile, until=arguments.get("until"), include_series=arguments.get("include_series", False))
    if name == "begin_session":
        metadata = arguments.get("metadata", {})
        if not isinstance(arguments.get("label"), str) or not isinstance(metadata, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()):
            raise UsageError("invalid begin_session arguments")
        return begin_session(arguments["label"], [f"{key}={value}" for key, value in metadata.items()])
    if name == "end_session":
        if not isinstance(arguments.get("token"), str) or not isinstance(arguments.get("include_series", False), bool):
            raise UsageError("invalid end_session arguments")
        return end_session(arguments["token"], profile, include_series=arguments.get("include_series", False))
    raise UsageError("unsupported tool")


def rpc_error(identifier: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": identifier, "error": error}


def mcp_main() -> int:
    while True:
        raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if not raw:
            break
        try:
            if len(raw) > 1024 * 1024:
                raise ValueError("request exceeds 1 MiB")
            request = strict_json_loads(raw)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
                emit(rpc_error(request.get("id") if isinstance(request, dict) else None, -32600, "Invalid Request"))
                continue
            identifier = request.get("id")
            method = request["method"]
            params = request.get("params", {})
            if method == "notifications/initialized":
                continue
            if method == "initialize":
                if not isinstance(params, dict) or not isinstance(params.get("protocolVersion"), str):
                    emit(rpc_error(identifier, -32602, "Invalid params"))
                    continue
                offered = params["protocolVersion"]
                negotiated = offered if offered in MCP_VERSIONS else MCP_VERSIONS[-1]
                emit({"jsonrpc": "2.0", "id": identifier, "result": {"protocolVersion": negotiated, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "supermicro-observability", "version": VERSION}, "instructions": "Read-only bounded local monitoring. Optional data may be disabled or missing. Never infer causation or cooling safety from telemetry. This server cannot control lifecycle, run arbitrary PromQL, inspect processes, or access hardware directly."}})
                continue
            if method == "ping":
                emit({"jsonrpc": "2.0", "id": identifier, "result": {}})
                continue
            if method == "tools/list":
                emit({"jsonrpc": "2.0", "id": identifier, "result": {"tools": annotated_tools()}})
                continue
            if method == "tools/call":
                if not isinstance(params, dict) or not isinstance(params.get("name"), str):
                    emit(rpc_error(identifier, -32602, "Invalid params"))
                    continue
                try:
                    structured = mcp_tool_call(params["name"], params.get("arguments", {}))
                    emit({"jsonrpc": "2.0", "id": identifier, "result": {"content": [{"type": "text", "text": json_bytes(structured).decode("utf-8")}], "structuredContent": structured, "isError": structured.get("status") in {"error", "unavailable"}}})
                except ObservationError as error:
                    structured = error_envelope(params["name"], params.get("arguments", {}).get("profile") if isinstance(params.get("arguments"), dict) else None, error)
                    emit({"jsonrpc": "2.0", "id": identifier, "result": {"content": [{"type": "text", "text": json_bytes(structured).decode("utf-8")}], "structuredContent": structured, "isError": True}})
                continue
            if identifier is not None:
                emit(rpc_error(identifier, -32601, "Method not found"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            emit(rpc_error(None, -32700, "Parse error", str(error)[:128]))
        except BrokenPipeError:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
