# v0.3.0 release notes

Version 0.3.0 adds an agent-first observation surface without expanding the
monitoring network or hardware boundary.

## Highlights

- A bounded JSON CLI for status, metric catalog, snapshots, window summaries,
  and explicitly labeled observation sessions.
- A local STDIO MCP adapter exposing the same six read-only operations for local
  or SSH-launched clients.
- A versioned JSON schema, visibly synthetic output example, fixed exit codes,
  finite-number enforcement, 24-hour windows, point/cardinality limits, and
  private atomic report output.
- Allowlisted aggregate system, GPU, thermal, monitoring-health, and benchmark
  profiles with identifier suppression and locally salted GPU re-aliasing.
- A combined custom Grafana dashboard for CPU, PSI, memory, storage, network,
  GPU, cached fan-controller, scrape-duration, and exporter-resource telemetry.
- Checkout-independent installation of the CLI, adapter, schema, examples, and
  documentation, with no-`sudo` observation commands.

Monitoring lifecycle, Compose configuration, existing databases, collector
access, listener policy, and fan-control separation are unchanged. No migration
is required. This release adds a public API and schema, so publication remains a
manual merge/tag/release checkpoint after review and clean CI.
