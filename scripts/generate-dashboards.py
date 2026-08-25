#!/usr/bin/env python3
"""Generate the checked-in Grafana dashboards without third-party packages."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "grafana" / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def target(expr, legend="", ref="A"):
    return {
        "datasource": DS,
        "editorMode": "code",
        "expr": expr,
        "legendFormat": legend,
        "range": True,
        "refId": ref,
    }


def panel(pid, title, kind, x, y, w, h, queries, unit="short", description=""):
    result = {
        "id": pid,
        "title": title,
        "type": kind,
        "datasource": DS,
        "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line",
                    "lineInterpolation": "linear",
                    "lineWidth": 1,
                    "fillOpacity": 8,
                    "showPoints": "never",
                    "spanNulls": True,
                },
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "targets": [target(*query) for query in queries],
    }
    if kind in {"stat", "gauge"}:
        result["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "orientation": "auto",
            "textMode": "auto",
            "colorMode": "value",
            "graphMode": "area" if kind == "stat" else "none",
            "justifyMode": "auto",
        }
    return result


def row(pid, title, y):
    return {
        "id": pid,
        "title": title,
        "type": "row",
        "collapsed": False,
        "panels": [],
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
    }


def hide_legend(result, *, hide_axes=False):
    result["options"]["legend"]["showLegend"] = False
    if hide_axes:
        result["fieldConfig"]["defaults"]["custom"]["axisPlacement"] = "hidden"
    return result


def text_stat(result):
    result["options"]["graphMode"] = "none"
    result["options"]["textMode"] = "value_and_name"
    return result


def dashboard(uid, title, tags, panels, variables=None):
    return {
        "annotations": {"list": []},
        "editable": False,
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "id": None,
        "links": [],
        "liveNow": True,
        "panels": panels,
        "refresh": "1s",
        "schemaVersion": 41,
        "tags": ["host-observability", *tags],
        "templating": {"list": variables or []},
        "time": {"from": "now-15m", "to": "now"},
        "timepicker": {
            "refresh_intervals": ["500ms", "1s", "2s", "5s", "10s", "30s", "1m", "5m"],
            "time_options": ["5m", "15m", "30m", "1h", "6h", "12h", "24h", "7d"],
        },
        "timezone": "browser",
        "title": title,
        "uid": uid,
        "version": 1,
        "weekStart": "",
    }


DISK_VARIABLE = {
    "name": "disk",
    "label": "Disk device",
    "type": "query",
    "datasource": DS,
    "definition": 'label_values(node_disk_read_bytes_total{job="node-fast"}, device)',
    "query": {
        "query": 'label_values(node_disk_read_bytes_total{job="node-fast"}, device)',
        "refId": "disk-variable",
    },
    "refresh": 1,
    "includeAll": True,
    "multi": True,
    "allValue": ".*",
    "current": {"selected": True, "text": "All", "value": "$__all"},
    "options": [],
}


DASHBOARDS = {
    "combined-custom.json": dashboard(
        "sm-combined-custom",
        "Combined Custom / Host + GPU + Cooling",
        ["combined", "custom"],
        [
            row(1, "Host summary", 0),
            hide_legend(panel(2, "CPU utilization", "timeseries", 0, 1, 12, 8, [("100 - rate(node_cpu_seconds_total{job=\"node-fast\",mode=\"idle\"}[30s]) * 100", "", "A")], "percent"), hide_axes=True),
            panel(3, "Memory", "timeseries", 12, 1, 12, 8, [("node_memory_MemTotal_bytes{job=\"node-fast\"} - node_memory_MemAvailable_bytes{job=\"node-fast\"}", "used", "A"), ("node_memory_MemAvailable_bytes{job=\"node-fast\"}", "available", "B"), ("node_memory_Cached_bytes{job=\"node-fast\"}", "cache", "C")], "bytes"),
            text_stat(panel(4, "CPU frequency", "stat", 0, 9, 12, 4, [("avg(node_cpu_scaling_frequency_hertz{job=\"node-slow\"})", "current average", "A")], "hertz")),
            text_stat(panel(5, "Memory utilization", "stat", 12, 9, 12, 4, [("100 * (1 - sum(node_memory_MemAvailable_bytes{job=\"node-fast\"}) / sum(node_memory_MemTotal_bytes{job=\"node-fast\"}))", "used", "A")], "percent")),
            row(10, "GPU 0", 13),
            panel(11, "Utilization", "timeseries", 0, 14, 8, 8, [("supermicro_gpu_utilization_percent{gpu_index=\"0\"}", "current", "A")], "percent"),
            panel(12, "Memory used", "timeseries", 8, 14, 8, 8, [("supermicro_gpu_memory_used_bytes{gpu_index=\"0\"}", "used", "A")], "bytes"),
            panel(13, "Temperature", "timeseries", 16, 14, 4, 8, [("supermicro_gpu_temperature_celsius{gpu_index=\"0\"}", "temperature", "A")], "celsius"),
            panel(14, "Power", "timeseries", 20, 14, 4, 8, [("supermicro_gpu_power_draw_watts{gpu_index=\"0\"}", "power", "A")], "watt"),
            panel(15, "Fan target", "timeseries", 0, 22, 8, 7, [("supermicro_gpu_fan_speed_percent{gpu_index=\"0\"}", "target", "A")], "percent"),
            text_stat(panel(16, "Clocks", "stat", 8, 22, 8, 7, [("supermicro_gpu_graphics_clock_hertz{gpu_index=\"0\"}", "graphics", "A"), ("supermicro_gpu_memory_clock_hertz{gpu_index=\"0\"}", "memory", "B")], "hertz")),
            text_stat(panel(17, "PCIe link", "stat", 16, 22, 8, 7, [("supermicro_gpu_pcie_link_generation{gpu_index=\"0\"}", "generation", "A"), ("supermicro_gpu_pcie_link_width{gpu_index=\"0\"}", "width", "B")], "short")),
            row(20, "GPU 1", 29),
            panel(21, "Utilization", "timeseries", 0, 30, 8, 8, [("supermicro_gpu_utilization_percent{gpu_index=\"1\"}", "current", "A")], "percent"),
            panel(22, "Memory used", "timeseries", 8, 30, 8, 8, [("supermicro_gpu_memory_used_bytes{gpu_index=\"1\"}", "used", "A")], "bytes"),
            panel(23, "Temperature", "timeseries", 16, 30, 4, 8, [("supermicro_gpu_temperature_celsius{gpu_index=\"1\"}", "temperature", "A")], "celsius"),
            panel(24, "Power", "timeseries", 20, 30, 4, 8, [("supermicro_gpu_power_draw_watts{gpu_index=\"1\"}", "power", "A")], "watt"),
            panel(25, "Fan target", "timeseries", 0, 38, 8, 7, [("supermicro_gpu_fan_speed_percent{gpu_index=\"1\"}", "target", "A")], "percent"),
            text_stat(panel(26, "Clocks", "stat", 8, 38, 8, 7, [("supermicro_gpu_graphics_clock_hertz{gpu_index=\"1\"}", "graphics", "A"), ("supermicro_gpu_memory_clock_hertz{gpu_index=\"1\"}", "memory", "B")], "hertz")),
            text_stat(panel(27, "PCIe link", "stat", 16, 38, 8, 7, [("supermicro_gpu_pcie_link_generation{gpu_index=\"1\"}", "generation", "A"), ("supermicro_gpu_pcie_link_width{gpu_index=\"1\"}", "width", "B")], "short")),
            row(30, "Cooling telemetry", 45),
            hide_legend(panel(31, "Fan RPM", "timeseries", 0, 46, 8, 8, [("supermicro_fan_speed_rpm", "", "A")], "rpm", "Cached fan-controller telemetry; monitoring does not poll IPMI or control fans.")),
            hide_legend(panel(32, "Controller temperatures", "timeseries", 8, 46, 8, 8, [("supermicro_fan_temperature_celsius", "", "A")], "celsius", "Aggregated cached controller inputs; values do not validate a cooling policy.")),
            panel(33, "Zone duty (IPMI)", "timeseries", 16, 46, 8, 8, [("supermicro_fan_zone_duty_percent", "{{zone}}", "A")], "percent", "Cached fan-controller telemetry; a missing series does not imply a safe cooling state."),
            row(40, "Storage and network", 54),
            panel(41, "Disk throughput", "timeseries", 0, 55, 12, 8, [("rate(node_disk_read_bytes_total{job=\"node-fast\",device=~\"$disk\"}[1m])", "{{device}} read", "A"), ("rate(node_disk_written_bytes_total{job=\"node-fast\",device=~\"$disk\"}[1m])", "{{device}} write", "B")], "Bps", "Use the dashboard disk control to select the reviewed mapped-root device."),
            panel(42, "Network throughput", "timeseries", 12, 55, 12, 8, [("rate(node_network_receive_bytes_total{job=\"node-fast\"}[1m])", "{{device}} RX", "A"), ("rate(node_network_transmit_bytes_total{job=\"node-fast\"}[1m])", "{{device}} TX", "B")], "Bps"),
            panel(43, "Disk I/O latency", "timeseries", 0, 63, 8, 8, [("rate(node_disk_read_time_seconds_total{job=\"node-fast\",device=~\"$disk\"}[1m]) / clamp_min(rate(node_disk_reads_completed_total{job=\"node-fast\",device=~\"$disk\"}[1m]), 0.001)", "{{device}} read", "A"), ("rate(node_disk_write_time_seconds_total{job=\"node-fast\",device=~\"$disk\"}[1m]) / clamp_min(rate(node_disk_writes_completed_total{job=\"node-fast\",device=~\"$disk\"}[1m]), 0.001)", "{{device}} write", "B")], "s"),
            panel(44, "Filesystem used", "timeseries", 8, 63, 8, 8, [("1 - node_filesystem_avail_bytes{job=\"node-slow\",fstype!~\"tmpfs|ramfs\"} / node_filesystem_size_bytes{job=\"node-slow\",fstype!~\"tmpfs|ramfs\"}", "{{mountpoint}}", "A")], "percentunit"),
            panel(45, "Network drops", "timeseries", 16, 63, 8, 8, [("rate(node_network_receive_errs_total{job=\"node-fast\"}[1m]) + rate(node_network_receive_drop_total{job=\"node-fast\"}[1m])", "{{device}} RX", "A"), ("rate(node_network_transmit_errs_total{job=\"node-fast\"}[1m]) + rate(node_network_transmit_drop_total{job=\"node-fast\"}[1m])", "{{device}} TX", "B")], "pps"),
            row(50, "CPU detail", 71),
            panel(51, "CPU modes", "timeseries", 0, 72, 12, 8, [("sum by (mode) (rate(node_cpu_seconds_total{job=\"node-fast\"}[30s])) * 100", "{{mode}}", "A")], "percent"),
            panel(52, "PSI waiting time", "timeseries", 12, 72, 12, 8, [("rate(node_pressure_cpu_waiting_seconds_total{job=\"node-fast\"}[30s])", "CPU some", "A"), ("rate(node_pressure_memory_waiting_seconds_total{job=\"node-fast\"}[30s])", "memory some", "B"), ("rate(node_pressure_io_waiting_seconds_total{job=\"node-fast\"}[30s])", "I/O some", "C")], "percentunit"),
            row(60, "GPU throttling", 80),
            panel(61, "Throttle reasons", "timeseries", 0, 81, 24, 8, [("supermicro_gpu_throttle_reason_active", "GPU {{gpu_index}} {{reason}}", "A")], "bool"),
            row(70, "Monitoring overhead", 89),
            panel(71, "Scrape duration", "timeseries", 0, 90, 8, 8, [("scrape_duration_seconds", "{{job}}", "A")], "s"),
            panel(72, "Exporter CPU", "timeseries", 8, 90, 8, 8, [("sum by (job) (rate(process_cpu_seconds_total{job!=\"node-fast\"}[1m])) * 100", "{{job}}", "A")], "percent"),
            panel(73, "Exporter RSS", "timeseries", 16, 90, 8, 8, [("max by (job) (process_resident_memory_bytes)", "{{job}}", "A")], "bytes"),
        ],
        [DISK_VARIABLE],
    ),
    "live-overview.json": dashboard(
        "sm-live",
        "Live CPU / GPU / I/O / Network",
        ["live"],
        [
            panel(1, "CPU busy", "stat", 0, 0, 4, 4, [("100 - avg(rate(node_cpu_seconds_total{job=\"node-fast\",mode=\"idle\"}[30s])) * 100", "CPU", "A")], "percent"),
            panel(2, "GPU utilization", "stat", 4, 0, 8, 4, [("supermicro_gpu_utilization_percent", "GPU {{gpu_index}}", "A")], "percent"),
            panel(3, "GPU 1s peak", "stat", 12, 0, 8, 4, [("supermicro_gpu_utilization_1s_percent_max", "GPU {{gpu_index}}", "A")], "percent"),
            panel(4, "GPU sample age", "stat", 20, 0, 4, 4, [("supermicro_gpu_sample_age_seconds", "age", "A")], "s"),
            panel(5, "CPU per core", "timeseries", 0, 4, 12, 8, [("100 - rate(node_cpu_seconds_total{job=\"node-fast\",mode=\"idle\"}[30s]) * 100", "CPU {{cpu}}", "A")], "percent"),
            panel(6, "GPU utilization and rolling peak", "timeseries", 12, 4, 12, 8, [("supermicro_gpu_utilization_percent", "GPU {{gpu_index}} current", "A"), ("supermicro_gpu_utilization_1s_percent_max", "GPU {{gpu_index}} peak", "B")], "percent"),
            panel(7, "Selected-disk throughput", "timeseries", 0, 12, 8, 7, [("rate(node_disk_read_bytes_total{job=\"node-fast\",device=~\"$disk\"}[30s])", "{{device}} read", "A"), ("rate(node_disk_written_bytes_total{job=\"node-fast\",device=~\"$disk\"}[30s])", "{{device}} write", "B")], "Bps"),
            panel(8, "Network throughput", "timeseries", 8, 12, 8, 7, [("rate(node_network_receive_bytes_total{job=\"node-fast\"}[30s])", "{{device}} RX", "A"), ("rate(node_network_transmit_bytes_total{job=\"node-fast\"}[30s])", "{{device}} TX", "B")], "Bps"),
            panel(9, "GPU power", "timeseries", 16, 12, 8, 7, [("supermicro_gpu_power_draw_watts", "GPU {{gpu_index}}", "A"), ("supermicro_gpu_power_draw_1s_watts_max", "GPU {{gpu_index}} 1s max", "B")], "watt"),
        ],
        [DISK_VARIABLE],
    ),
    "cpu-memory-pressure.json": dashboard(
        "sm-cpu-memory",
        "CPU Cores / PSI / Memory / Scheduler",
        ["cpu", "memory"],
        [
            panel(1, "Per-core busy", "timeseries", 0, 0, 12, 8, [("100 - rate(node_cpu_seconds_total{job=\"node-fast\",mode=\"idle\"}[30s]) * 100", "CPU {{cpu}}", "A")], "percent"),
            panel(2, "CPU modes", "timeseries", 12, 0, 12, 8, [("sum by (mode) (rate(node_cpu_seconds_total{job=\"node-fast\"}[30s])) * 100", "{{mode}}", "A")], "percent"),
            panel(3, "PSI waiting time", "timeseries", 0, 8, 12, 8, [("rate(node_pressure_cpu_waiting_seconds_total{job=\"node-fast\"}[30s])", "CPU some", "A"), ("rate(node_pressure_memory_waiting_seconds_total{job=\"node-fast\"}[30s])", "memory some", "B"), ("rate(node_pressure_io_waiting_seconds_total{job=\"node-fast\"}[30s])", "I/O some", "C")], "percentunit"),
            panel(4, "Memory", "timeseries", 12, 8, 12, 8, [("node_memory_MemTotal_bytes{job=\"node-fast\"} - node_memory_MemAvailable_bytes{job=\"node-fast\"}", "used", "A"), ("node_memory_MemAvailable_bytes{job=\"node-fast\"}", "available", "B"), ("node_memory_Cached_bytes{job=\"node-fast\"}", "cache", "C")], "bytes"),
            panel(5, "Scheduler running time", "timeseries", 0, 16, 8, 7, [("rate(node_schedstat_running_seconds_total{job=\"node-fast\"}[30s])", "CPU {{cpu}}", "A")], "cores"),
            panel(6, "Scheduler waiting time", "timeseries", 8, 16, 8, 7, [("rate(node_schedstat_waiting_seconds_total{job=\"node-fast\"}[30s])", "CPU {{cpu}}", "A")], "s"),
            panel(7, "Context / VM activity", "timeseries", 16, 16, 8, 7, [("rate(node_vmstat_pgmajfault{job=\"node-fast\"}[30s])", "major faults", "A"), ("rate(node_vmstat_oom_kill{job=\"node-fast\"}[5m])", "OOM kills", "B")], "ops"),
        ],
    ),
    "gpu-detail.json": dashboard(
        "sm-gpu",
        "NVIDIA GPU Detail / One-second Peaks",
        ["gpu"],
        [
            panel(1, "Sampler healthy", "stat", 0, 0, 4, 4, [("supermicro_gpu_sampler_up", "up", "A")], "bool"),
            panel(2, "Sample cadence", "stat", 4, 0, 8, 4, [("supermicro_gpu_sample_interval_seconds", "GPU {{gpu_index}}", "A")], "s"),
            panel(3, "Temperature", "stat", 12, 0, 8, 4, [("supermicro_gpu_temperature_celsius", "GPU {{gpu_index}}", "A")], "celsius"),
            panel(4, "P-state", "stat", 20, 0, 4, 4, [("supermicro_gpu_performance_state", "GPU {{gpu_index}}", "A")], "short"),
            panel(5, "GPU utilization", "timeseries", 0, 4, 12, 8, [("supermicro_gpu_utilization_percent", "GPU {{gpu_index}} current", "A"), ("supermicro_gpu_utilization_1s_percent_average", "GPU {{gpu_index}} 1s avg", "B"), ("supermicro_gpu_utilization_1s_percent_max", "GPU {{gpu_index}} 1s max", "C")], "percent"),
            panel(6, "Memory utilization", "timeseries", 12, 4, 12, 8, [("supermicro_gpu_memory_utilization_percent", "GPU {{gpu_index}} current", "A"), ("supermicro_gpu_memory_utilization_1s_percent_max", "GPU {{gpu_index}} 1s max", "B")], "percent"),
            panel(7, "Power", "timeseries", 0, 12, 8, 7, [("supermicro_gpu_power_draw_watts", "GPU {{gpu_index}} current", "A"), ("supermicro_gpu_power_draw_1s_watts_average", "GPU {{gpu_index}} 1s avg", "B"), ("supermicro_gpu_power_draw_1s_watts_max", "GPU {{gpu_index}} 1s max", "C")], "watt"),
            panel(8, "Clocks", "timeseries", 8, 12, 8, 7, [("supermicro_gpu_graphics_clock_hertz", "GPU {{gpu_index}} graphics", "A"), ("supermicro_gpu_memory_clock_hertz", "GPU {{gpu_index}} memory", "B")], "hertz"),
            panel(9, "PCIe link", "timeseries", 16, 12, 8, 7, [("supermicro_gpu_pcie_link_generation", "GPU {{gpu_index}} generation", "A"), ("supermicro_gpu_pcie_link_width", "GPU {{gpu_index}} width", "B")], "short"),
            panel(10, "Throttle reasons", "timeseries", 0, 19, 12, 7, [("supermicro_gpu_throttle_reason_active", "GPU {{gpu_index}} {{reason}}", "A")], "bool"),
            panel(11, "Memory used", "timeseries", 12, 19, 6, 7, [("supermicro_gpu_memory_used_bytes", "GPU {{gpu_index}}", "A")], "bytes"),
            panel(12, "Fan target", "timeseries", 18, 19, 6, 7, [("supermicro_gpu_fan_speed_percent", "GPU {{gpu_index}}", "A")], "percent"),
        ],
    ),
    "thermal-fans.json": dashboard(
        "sm-thermal-fans",
        "Thermal / Fan Control",
        ["thermal", "fans"],
        [
            panel(1, "Controller active", "stat", 0, 0, 6, 4, [("supermicro_fan_controller_active", "active", "A")], "bool"),
            panel(2, "Fail-safe", "stat", 6, 0, 6, 4, [("supermicro_fan_controller_failsafe", "fail-safe", "A")], "bool"),
            panel(3, "IPMI read healthy", "stat", 12, 0, 6, 4, [("supermicro_fan_sensor_read_healthy", "healthy", "A")], "bool"),
            panel(4, "Metric age", "stat", 18, 0, 6, 4, [("time() - supermicro_fan_sample_timestamp_seconds", "age", "A")], "s"),
            panel(5, "Fan RPM", "timeseries", 0, 4, 12, 8, [("supermicro_fan_speed_rpm", "{{fan}}", "A")], "rpm"),
            panel(6, "Zone duty", "timeseries", 12, 4, 12, 8, [("supermicro_fan_zone_duty_percent", "{{zone}}", "A")], "percent"),
            panel(7, "Controller temperatures", "timeseries", 0, 12, 12, 8, [("supermicro_fan_temperature_celsius", "{{sensor_group}}", "A")], "celsius"),
            panel(8, "Kernel hwmon temperatures", "timeseries", 12, 12, 12, 8, [("node_hwmon_temp_celsius{job=\"node-slow\"}", "{{chip}} {{sensor}}", "A"), ("node_thermal_zone_temp{job=\"node-slow\"}", "{{zone}}", "B")], "celsius"),
        ],
    ),
    "storage-network.json": dashboard(
        "sm-storage-network",
        "Disk / Network / Storage Health",
        ["storage", "network"],
        [
            panel(1, "Disk throughput", "timeseries", 0, 0, 12, 8, [("rate(node_disk_read_bytes_total{job=\"node-fast\",device=~\"$disk\"}[1m])", "{{device}} read", "A"), ("rate(node_disk_written_bytes_total{job=\"node-fast\",device=~\"$disk\"}[1m])", "{{device}} write", "B")], "Bps"),
            panel(2, "Disk I/O latency", "timeseries", 12, 0, 12, 8, [("rate(node_disk_read_time_seconds_total{job=\"node-fast\",device=~\"$disk\"}[1m]) / clamp_min(rate(node_disk_reads_completed_total{job=\"node-fast\",device=~\"$disk\"}[1m]), 0.001)", "{{device}} read", "A"), ("rate(node_disk_write_time_seconds_total{job=\"node-fast\",device=~\"$disk\"}[1m]) / clamp_min(rate(node_disk_writes_completed_total{job=\"node-fast\",device=~\"$disk\"}[1m]), 0.001)", "{{device}} write", "B")], "s"),
            panel(3, "Filesystem used", "timeseries", 0, 8, 8, 7, [("1 - node_filesystem_avail_bytes{job=\"node-slow\",fstype!~\"tmpfs|ramfs\"} / node_filesystem_size_bytes{job=\"node-slow\",fstype!~\"tmpfs|ramfs\"}", "{{mountpoint}}", "A")], "percentunit"),
            panel(4, "SMART health", "stat", 8, 8, 8, 7, [("smartctl_device_smart_status", "{{device}}", "A")], "bool"),
            panel(5, "NVMe wear / temperature", "timeseries", 16, 8, 8, 7, [("smartctl_device_percentage_used", "{{device}} wear", "A"), ("smartctl_device_temperature", "{{device}} temperature", "B")], "short"),
            panel(6, "Network throughput", "timeseries", 0, 15, 12, 8, [("rate(node_network_receive_bytes_total{job=\"node-fast\"}[1m])", "{{device}} RX", "A"), ("rate(node_network_transmit_bytes_total{job=\"node-fast\"}[1m])", "{{device}} TX", "B")], "Bps"),
            panel(7, "Network errors / drops", "timeseries", 12, 15, 12, 8, [("rate(node_network_receive_errs_total{job=\"node-fast\"}[1m]) + rate(node_network_receive_drop_total{job=\"node-fast\"}[1m])", "{{device}} RX", "A"), ("rate(node_network_transmit_errs_total{job=\"node-fast\"}[1m]) + rate(node_network_transmit_drop_total{job=\"node-fast\"}[1m])", "{{device}} TX", "B")], "pps"),
        ],
        [DISK_VARIABLE],
    ),
    "monitoring-overhead.json": dashboard(
        "sm-overhead",
        "Prometheus / Collector Overhead",
        ["overhead"],
        [
            panel(1, "Targets up", "stat", 0, 0, 12, 4, [("min by (job) (up)", "{{job}}", "A")], "bool"),
            panel(2, "Active series", "stat", 12, 0, 6, 4, [("prometheus_tsdb_head_series", "series", "A")], "short"),
            panel(3, "Prometheus storage", "stat", 18, 0, 6, 4, [("prometheus_tsdb_storage_blocks_bytes", "blocks", "A")], "bytes"),
            panel(4, "Scrape duration", "timeseries", 0, 4, 12, 8, [("scrape_duration_seconds", "{{job}}", "A")], "s"),
            panel(5, "Scrape samples", "timeseries", 12, 4, 12, 8, [("scrape_samples_post_metric_relabeling", "{{job}}", "A")], "short"),
            panel(6, "Exporter CPU", "timeseries", 0, 12, 8, 7, [("sum by (job) (rate(process_cpu_seconds_total{job!=\"node-fast\"}[1m])) * 100", "{{job}}", "A")], "percent"),
            panel(7, "Exporter RSS", "timeseries", 8, 12, 8, 7, [("max by (job) (process_resident_memory_bytes)", "{{job}}", "A")], "bytes"),
            panel(8, "Sampler health", "timeseries", 16, 12, 8, 7, [("supermicro_gpu_sample_age_seconds", "age", "A"), ("increase(supermicro_gpu_sampler_restarts_total[5m])", "restarts", "B"), ("increase(supermicro_gpu_parse_errors_total[5m])", "parse errors", "C")], "short"),
        ],
    ),
    "containers.json": dashboard(
        "sm-containers",
        "Optional Container Metrics",
        ["containers", "optional"],
        [
            panel(1, "Container target", "stat", 0, 0, 6, 4, [("up{job=\"cadvisor\"}", "cAdvisor", "A")], "bool", "Enable with scripts/container-metrics on."),
            panel(2, "Container count", "stat", 6, 0, 6, 4, [("count(container_last_seen{job=\"cadvisor\",name!=\"\"})", "containers", "A")], "short"),
            panel(3, "CPU", "timeseries", 0, 4, 12, 8, [("sum by (name) (rate(container_cpu_usage_seconds_total{job=\"cadvisor\",name!=\"\"}[1m])) * 100", "{{name}}", "A")], "percent"),
            panel(4, "Memory working set", "timeseries", 12, 4, 12, 8, [("container_memory_working_set_bytes{job=\"cadvisor\",name!=\"\"}", "{{name}}", "A")], "bytes"),
            panel(5, "Network RX/TX", "timeseries", 0, 12, 12, 8, [("sum by (name) (rate(container_network_receive_bytes_total{job=\"cadvisor\",name!=\"\"}[1m]))", "{{name}} RX", "A"), ("sum by (name) (rate(container_network_transmit_bytes_total{job=\"cadvisor\",name!=\"\"}[1m]))", "{{name}} TX", "B")], "Bps"),
            panel(6, "Filesystem I/O", "timeseries", 12, 12, 12, 8, [("sum by (name,operation) (rate(container_fs_io_time_seconds_total{job=\"cadvisor\",name!=\"\"}[1m]))", "{{name}} {{operation}}", "A")], "s"),
        ],
    ),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, content in DASHBOARDS.items():
        (OUT / filename).write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
