# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [Unreleased]

### Changed

- Made checkout-local `make run`, `make stop`, and related commands the default
  workflow, with no system installation required.
- Renamed the explicit system-promotion workflow to `make install-system` and
  prevented either lifecycle from taking over the other while it is running.
- Made systemd installation disabled by default and prevented installation from
  starting the service, for on-demand use.
- Made installation independent of the source checkout by separating immutable
  application files, administrator configuration, credentials, and persistent
  state across standard system paths.
- Allowed Grafana alone to bind to one exact private address while keeping every
  metrics endpoint on loopback.
- Made Grafana's container health probe follow its configured bind address.
- Replaced committed storage identities with private, stable by-id host profiles.
- Made NVIDIA, SMART, and fan-textfile integration explicit optional features.
- Keyed GPU rolling state by UUID and added UUID, index, or salted-alias output
  modes under the generic `gpu_id` label.
- Replaced fixed disk dashboard queries with a user-selectable device variable.
- Made monitoring installation and rollback independent of fan control.

### Added

- Added checkout-local lifecycle, bind, password, status, and configuration
  targets plus a default command summary.
- Added `make install-system` (`make install` alias) and an installed management
  command with lifecycle, configuration, password, uninstall, and
  confirmation-gated purge operations.
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
