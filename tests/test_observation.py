from __future__ import annotations

import datetime as dt
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import observation as obs  # noqa: E402


class QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass


class PrometheusFixture:
    def __init__(self, responses=None, *, malformed=False, delay=0.0):
        self.responses = responses or {}
        self.malformed = malformed
        self.delay = delay
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append(self.path)
                if owner.delay:
                    time.sleep(owner.delay)
                if self.path.startswith("/-/ready"):
                    body = b"Prometheus is Ready.\n"
                elif owner.malformed:
                    body = b"not-json"
                else:
                    parsed = urllib.parse.urlsplit(self.path)
                    params = urllib.parse.parse_qs(parsed.query)
                    query = params.get("query", [""])[0]
                    result = owner.responses.get(query, [])
                    result_type = "matrix" if parsed.path.endswith("query_range") else "vector"
                    body = json.dumps({"status": "success", "data": {"resultType": result_type, "result": result}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def log_message(self, format, *args):
                pass

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def client(self):
        return obs.PrometheusClient(f"http://127.0.0.1:{self.server.server_port}")


class TimeAndStatisticsTests(unittest.TestCase):
    def test_duration_and_timestamp_windows(self):
        end = dt.datetime(2030, 1, 2, tzinfo=dt.timezone.utc)
        start, resolved_end = obs.resolve_window("10m", now=end)
        self.assertEqual((resolved_end - start).total_seconds(), 600)
        start, resolved_end = obs.resolve_window("2030-01-01T23:00:00-01:00", "2030-01-02T01:00:00Z")
        self.assertEqual((resolved_end - start).total_seconds(), 3600)
        with self.assertRaises(obs.UsageError):
            obs.parse_duration("25h")
        with self.assertRaises(obs.UsageError):
            obs.parse_timestamp("2030-01-02T03:04:05")

    def test_nearest_rank_percentile(self):
        self.assertEqual(obs.nearest_rank_p95(list(range(1, 101))), 95)
        self.assertEqual(obs.nearest_rank_p95([7]), 7)

    def test_non_finite_values_are_rejected(self):
        for value in ("NaN", "+Inf", "-Inf"):
            with self.assertRaises(obs.ObservationError):
                obs.finite_number(value)
        with self.assertRaises(obs.ObservationError):
            obs.json_bytes({"value": float("nan")})


class SessionAndOutputTests(unittest.TestCase):
    def test_tokens_are_self_contained_and_checksummed(self):
        payload = {"v": 1, "started_at": "2030-01-02T03:04:05.000Z", "label": "eval-17", "metadata": {"commit": "abc123"}}
        token = obs.encode_token(payload)
        self.assertEqual(obs.decode_token(token), payload)
        with self.assertRaises(obs.UsageError):
            obs.decode_token(token[:-1] + ("0" if token[-1] != "0" else "1"))

    def test_metadata_and_label_limits(self):
        self.assertEqual(obs.parse_metadata(["commit=abc123"]), {"commit": "abc123"})
        with self.assertRaises(obs.UsageError):
            obs.parse_metadata(["bad key=value"])
        with self.assertRaises(obs.UsageError):
            obs.validate_label("x" * 65)

    def test_atomic_output_is_private_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "report.json"
            obs.atomic_output(path, {"ok": True})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text()), {"ok": True})
            with self.assertRaises(obs.ObservationError) as caught:
                obs.atomic_output(path, {"ok": False})
            self.assertEqual(caught.exception.exit_code, obs.EXIT_OUTPUT)


class ExitCodeTests(unittest.TestCase):
    def test_fixed_usage_availability_data_and_output_codes(self):
        with mock.patch.object(obs, "emit") as emit:
            self.assertEqual(obs.cli_main(["summarize", "--since", "25h"]), obs.EXIT_USAGE)
            self.assertEqual(emit.call_args.args[0]["error"]["code"], "usage")
        with mock.patch.object(obs, "snapshot", side_effect=obs.PrometheusUnavailable()), mock.patch.object(obs, "emit"):
            self.assertEqual(obs.cli_main(["snapshot"]), obs.EXIT_UNAVAILABLE)
        with mock.patch.object(obs, "snapshot", side_effect=obs.ObservationError("malformed_response", "bad data")), mock.patch.object(obs, "emit"):
            self.assertEqual(obs.cli_main(["snapshot"]), obs.EXIT_DATA)
        with mock.patch.object(obs, "end_session", return_value={"status": "ok"}), mock.patch.object(
            obs, "atomic_output", side_effect=obs.ObservationError("output_exists", "exists", obs.EXIT_OUTPUT)
        ), mock.patch.object(obs, "emit"):
            self.assertEqual(obs.cli_main(["end", "token", "--output", "report.json"]), obs.EXIT_OUTPUT)


class PrivacyTests(unittest.TestCase):
    def test_gpu_alias_is_stable_and_raw_labels_are_suppressed(self):
        spec = next(item for item in obs.METRICS if item.id == "gpu.utilization")
        labels = {"gpu_id": "GPU-SENSITIVE", "gpu_uuid": "UUID-SENSITIVE", "gpu_name": "MODEL-SENSITIVE", "instance": "HOST-SENSITIVE"}
        dimensions, warnings = obs.safe_dimensions(labels, spec, "private-test-salt")
        self.assertEqual(dimensions, {"gpu": obs.gpu_alias("GPU-SENSITIVE", "private-test-salt")})
        self.assertNotIn("SENSITIVE", json.dumps(dimensions))
        dimensions, warnings = obs.safe_dimensions(labels, spec, None)
        self.assertEqual(dimensions, {})
        self.assertTrue(warnings)

    def test_only_allowlisted_job_and_reason_labels_survive(self):
        health = next(item for item in obs.METRICS if item.id == "health.target.up")
        throttle = next(item for item in obs.METRICS if item.id == "gpu.throttle.active")
        self.assertEqual(obs.safe_dimensions({"job": "node-fast", "instance": "secret"}, health, None)[0], {"job": "node-fast"})
        self.assertEqual(obs.safe_dimensions({"job": "attacker"}, health, None)[0], {})
        self.assertEqual(obs.safe_dimensions({"reason": "hardware_thermal", "gpu_id": "x"}, throttle, "salt")[0]["reason"], "hardware_thermal")


class FixtureTests(unittest.TestCase):
    NOW = dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)

    def _config(self):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "config.env"
        path.write_text("ENABLE_NVIDIA_GPU=true\nENABLE_SMART=false\nFAN_METRICS_MODE=disabled\nGPU_IDENTITY_SALT=fixture-private-salt\n")
        return temporary, path

    def test_snapshot_url_encoding_aliasing_and_partial_data(self):
        utilization = next(item for item in obs.METRICS if item.id == "gpu.utilization")
        responses = {
            utilization.query: [{"metric": {"gpu_id": "GPU-private", "gpu_name": "private-model"}, "value": [self.NOW.timestamp(), "42"]}],
        }
        temporary, path = self._config()
        with temporary, mock.patch.dict(os.environ, {"OBSERVABILITY_CONFIG_FILE": str(path)}), PrometheusFixture(responses) as fixture, mock.patch.object(obs, "profile_specs", return_value=[utilization]):
            result = obs.snapshot("gpu", client=fixture.client, now=self.NOW)
            self.assertEqual(result["status"], "ok")
            encoded_request = fixture.requests[-1]
            self.assertIn("query=supermicro_gpu_utilization_percent", encoded_request)
            self.assertNotIn("GPU-private", json.dumps(result))
            self.assertRegex(result["metrics"][0]["dimensions"]["gpu"], r"^gpu-[0-9a-f]{12}$")

    def test_disabled_optional_metric_is_successful(self):
        smart = next(item for item in obs.METRICS if item.id == "health.smart.passed")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.env"
            path.write_text("ENABLE_SMART=false\n")
            with mock.patch.dict(os.environ, {"OBSERVABILITY_CONFIG_FILE": str(path)}), PrometheusFixture() as fixture, mock.patch.object(obs, "profile_specs", return_value=[smart]):
                result = obs.snapshot("health", client=fixture.client, now=self.NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["metrics"][0]["availability"], "disabled")

    def test_missing_enabled_metric_makes_snapshot_partial(self):
        gpu = next(item for item in obs.METRICS if item.id == "gpu.power")
        temporary, path = self._config()
        with temporary, mock.patch.dict(os.environ, {"OBSERVABILITY_CONFIG_FILE": str(path)}), PrometheusFixture() as fixture, mock.patch.object(obs, "profile_specs", return_value=[gpu]):
            result = obs.snapshot("gpu", client=fixture.client, now=self.NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["metrics"][0]["availability"], "missing")

    def test_range_is_bounded_and_summary_is_deterministic(self):
        metric = next(item for item in obs.METRICS if item.id == "system.memory.available")
        values = [[self.NOW.timestamp() - 3 + index, str(index)] for index in range(4)]
        with PrometheusFixture({metric.query: [{"metric": {}, "values": values}]}) as fixture, mock.patch.object(obs, "profile_specs", return_value=[metric]):
            result = obs.summarize("3s", "system", client=fixture.client, now=self.NOW, include_series=True)
        summary = result["metrics"][0]["summary"]
        self.assertEqual(summary, {"min": 0.0, "mean": 1.5, "p95": 3.0, "max": 3.0, "points": 4, "coverage": 1.0})
        self.assertLessEqual(len(result["metrics"][0]["series"]), obs.MAX_RETURNED_POINTS)
        self.assertIn("step=1", fixture.requests[-1])

    def test_malformed_timeout_and_cardinality_fail_closed(self):
        with PrometheusFixture(malformed=True) as fixture:
            with self.assertRaises(obs.ObservationError):
                fixture.client.instant("up")
        with PrometheusFixture(delay=0.1) as fixture:
            client = obs.PrometheusClient(f"http://127.0.0.1:{fixture.server.server_port}", timeout=0.01)
            with self.assertRaises(obs.PrometheusUnavailable):
                client.ready()
        metric = next(item for item in obs.METRICS if item.id == "system.memory.available")
        too_many = [{"metric": {}, "value": [self.NOW.timestamp(), "1"]} for _ in range(129)]
        with PrometheusFixture({metric.query: too_many}) as fixture, mock.patch.object(obs, "profile_specs", return_value=[metric]):
            with self.assertRaises(obs.ObservationError) as caught:
                obs.snapshot("system", client=fixture.client, now=self.NOW)
        self.assertEqual(caught.exception.code, "cardinality_limit")


class MCPTests(unittest.TestCase):
    def test_tool_annotations_and_dispatch_for_every_tool(self):
        tools = obs.annotated_tools()
        self.assertEqual({tool["name"] for tool in tools}, {"observability_status", "metric_catalog", "snapshot", "summarize_window", "begin_session", "end_session"})
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] and not tool["annotations"]["destructiveHint"] for tool in tools))
        sentinel = {"status": "ok"}
        with mock.patch.object(obs, "status", return_value=sentinel) as status_call:
            self.assertIs(obs.mcp_tool_call("observability_status", {}), sentinel)
            status_call.assert_called_once()
        with mock.patch.object(obs, "catalog", return_value=sentinel):
            self.assertIs(obs.mcp_tool_call("metric_catalog", {}), sentinel)
        with mock.patch.object(obs, "snapshot", return_value=sentinel):
            self.assertIs(obs.mcp_tool_call("snapshot", {"profile": "gpu"}), sentinel)
        with mock.patch.object(obs, "summarize", return_value=sentinel):
            self.assertIs(obs.mcp_tool_call("summarize_window", {"since": "10m"}), sentinel)
        with mock.patch.object(obs, "begin_session", return_value=sentinel):
            self.assertIs(obs.mcp_tool_call("begin_session", {"label": "eval", "metadata": {"commit": "abc"}}), sentinel)
        with mock.patch.object(obs, "end_session", return_value=sentinel):
            self.assertIs(obs.mcp_tool_call("end_session", {"token": "token"}), sentinel)
        with self.assertRaises(obs.UsageError):
            obs.mcp_tool_call("snapshot", {"query": "up"})

    def test_stdio_transcript_negotiation_errors_and_stdout_cleanliness(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "metric_catalog", "arguments": {"profile": "system"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "not/supported"},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "snapshot", "arguments": {"query": "up"}}},
        ]
        process = subprocess.run(
            [str(PROJECT / "scripts" / "observe"), "mcp"],
            input="".join(json.dumps(item) + "\n" for item in requests), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        self.assertEqual(process.stderr, "")
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(len(responses), 6)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2026-07-28")
        self.assertEqual(responses[1]["result"], {})
        self.assertEqual(len(responses[2]["result"]["tools"]), 6)
        self.assertEqual(responses[3]["result"]["structuredContent"]["command"], "catalog")
        self.assertEqual(responses[4]["error"]["code"], -32601)
        self.assertTrue(responses[5]["result"]["isError"])
        self.assertEqual(responses[5]["result"]["structuredContent"]["error"]["code"], "usage")


if __name__ == "__main__":
    unittest.main()
