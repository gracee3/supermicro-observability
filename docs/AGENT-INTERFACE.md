# Agent observation interface

Version 0.3.0 provides one bounded, read-only observation implementation through
a JSON command-line interface and a newline-delimited JSON-RPC STDIO MCP server.
Both query only `http://127.0.0.1:9090`. They do not start monitoring, expose a
listener, accept arbitrary PromQL, inspect processes, or access hardware.

This design follows OpenAI guidance for
[agent-friendly CLIs](https://learn.chatgpt.com/use-cases/agent-friendly-clis)
and [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp).

## Commands

Run from a checkout:

```bash
scripts/observe status --json
scripts/observe catalog --profile benchmark --json
scripts/observe snapshot --profile benchmark --json
scripts/observe summarize --since 10m --profile benchmark --json
scripts/observe summarize --since 2026-08-24T12:00:00Z \
  --until 2026-08-24T12:10:00Z --profile system --json
scripts/observe begin --label eval-17 --metadata commit=abc123 --json
scripts/observe end SESSION_TOKEN --profile benchmark \
  --output .observability/eval-17.json --json
scripts/observe mcp
```

After optional system installation, use the same commands without `sudo`:

```bash
supermicro-observability observe status --json
supermicro-observability observe snapshot --profile benchmark --json
supermicro-observability mcp
```

Lifecycle remains human-controlled through the separately privileged management
commands. An unavailable stack returns structured remediation; observation never
attempts startup.

## Stable profiles

| Profile | Allowlisted metric families |
|---|---|
| `system` | Aggregate CPU utilization, memory used/available, CPU/memory/I/O pressure, disk and non-loopback network throughput, and OOM rate |
| `gpu` | Sampler health/age, utilization and one-second rollups, memory, power, temperature, clocks, performance state, PCIe state, and throttling |
| `thermal` | Maximum aggregate hwmon and thermal-zone temperatures plus optional fan-controller health, freshness, RPM, duty, and temperature |
| `health` | Target health and scrape duration for fixed jobs, Prometheus series/storage health, and aggregated SMART health |
| `benchmark` | Union of `system`, `gpu`, `thermal`, and `health`; the default for snapshots, summaries, and session completion |

The catalog is compiled into the tool. There is no user-supplied query field.
Metric IDs and units are stable within `observation-v1`; additions can be made
without changing existing records.

## Response and availability

Every response uses `schemas/observation-v1.schema.json`. Its envelope includes
`schema_version`, `command`, UTC `generated_at`, `status`, `source`, `metrics`,
and `warnings`, plus a `profile`, `window`, `session`, or structured `error` when
applicable. Each metric has an ID, unit, safe dimensions, and availability.
Snapshots contain `value`. Window records contain arithmetic `mean`,
nearest-rank `p95`, `min`, `max`, returned query-point count, and coverage.

- `ok` means all enabled requested families returned usable data.
- `partial` means enabled/core data was missing, stale, or had incomplete range
  coverage. Malformed or non-finite query data is an `error` instead.
- `unavailable` means loopback Prometheus could not be reached.
- Disabled optional collectors remain successful with metric availability
  `disabled`; absence does not fabricate a target failure.

The CLI rejects non-finite numbers. It emits one JSON document on stdout. Fixed
exit codes are `0` for a successful or partial observation, `2` for usage, `3`
for monitoring availability, `4` for query/data failure, and `5` for report
output failure.

## Bounds and report files

`--since` accepts a positive integer followed by `s`, `m`, or `h`, or an RFC
3339 timestamp. `--until` accepts RFC 3339. A window must be positive and no
longer than 24 hours. Range evaluation requests at most 600 points per series.
`--include-series` returns at most 120 points per series and 10,000 total points;
summaries are returned by default.

`begin` checks readiness and returns a versioned, checksummed, self-contained
token. It does not write a file or collect repository state. A label is limited
to 64 safe characters. Up to 16 explicit `key=value` metadata entries are
accepted with bounded keys and values. `end` uses the token start time and
refuses a session over 24 hours.

Only `end --output PATH` writes an implicit report. It creates parent
directories as needed, uses an atomic same-directory operation, sets mode
`0600`, and refuses to overwrite an existing file. This repository ignores
`.observability/`.

## Privacy and interpretation

Public results never return host, device, interface, container, sensor,
GPU-name, UUID, command, process, or workload labels. The only dimension keys
are fixed job names, fixed throttle reasons, and GPU aliases. GPU values stored
by Prometheus are re-pseudonymized with the private local identity salt; if the
salt cannot be read, the GPU dimension is omitted rather than exposing the
stored identifier. Pseudonyms support correlation but are not anonymity.

Aggregate temperature or fan telemetry does not demonstrate cooling safety.
Correlation does not establish workload or hardware causation. Preserve the
methodology and publication limits in `docs/METHODOLOGY.md` and
`docs/PUBLICATION-ETHICS.md` when retaining or sharing reports.

`examples/observation-synthetic.json` is deliberately invented and contains no
host capture.

## MCP clients

The MCP adapter reads one JSON-RPC request per line on stdin and writes protocol
responses only to stdout. It implements `initialize`, `ping`, `tools/list`, and
`tools/call`, negotiates supported MCP protocol versions through `2026-07-28`,
and exposes these read-only/non-destructive tools:

- `observability_status`
- `metric_catalog`
- `snapshot`
- `summarize_window`
- `begin_session`
- `end_session`

Tool results contain `structuredContent` and a JSON text fallback. The server
has no resources, prompts, HTTP transport, lifecycle tool, or arbitrary query
tool.

Register a checkout-local server with Codex:

```bash
codex mcp add supermicro-observability -- \
  /ABSOLUTE/PATH/TO/supermicro-observability/scripts/observe mcp
```

Register an installed server:

```bash
codex mcp add supermicro-observability -- \
  /usr/local/sbin/supermicro-observability mcp
```

From a trusted T14 or another client that already has SSH access, keep all
metrics endpoints on the monitoring host and transport only STDIO:

```bash
codex mcp add supermicro-observability -- \
  ssh -T MONITORING_HOST /usr/local/sbin/supermicro-observability mcp
```

The equivalent generic-client process configuration is an executable plus an
argument array, for example `command = "ssh"` with arguments `-T`,
`MONITORING_HOST`, `/usr/local/sbin/supermicro-observability`, and `mcp`.
Consult that client's current documentation for its configuration format. This
repository intentionally commits no path-dependent `.codex/config.toml`.

## Troubleshooting

Start with `observe status --json`. If it reports `monitoring_unavailable`, ask
a human operator to inspect lifecycle and service health. Do not work around the
boundary by opening port 9090 or starting containers. A `partial` result should
be interpreted metric by metric: check `availability` and `warnings`, and do
not substitute missing optional data with zero.
