# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [Unreleased]

### Changed

- Replaced committed storage identities with private, stable by-id host profiles.
- Made NVIDIA, SMART, and fan-textfile integration explicit optional features.
- Keyed GPU rolling state by UUID and added UUID, index, or salted-alias output
  modes under the generic `gpu_id` label.
- Replaced fixed disk dashboard queries with a user-selectable device variable.
- Made monitoring installation and rollback independent of fan control.

### Added

- `configure-host` and `doctor` commands with fail-closed validation.
- Generated file-discovery targets that avoid failures for disabled collectors.
- A generic configuration guide, fan metric contract, and redacted deployment
  case-study structure.

## [0.1.0] - 2026-08-17

### Added

- Loopback-only Prometheus, Grafana, node_exporter, NVML, SMART, and optional
  cAdvisor services with pinned container-image digests.
- Persistent standard-library Rust GPU sampler with 250 ms sampling, 500 ms
  scraping, one-second rolling aggregates, stale-state reporting, and tests.
- Provisioned dashboards, storage guardrails, monitoring modes, validation,
  overhead measurement, systemd startup, and rollback tooling.
- Publication metadata, methodology, safety boundaries, ethics disclosure,
  contribution guidance, and third-party attribution.

[0.1.0]: https://github.com/gracee3/supermicro-observability/releases/tag/v0.1.0
