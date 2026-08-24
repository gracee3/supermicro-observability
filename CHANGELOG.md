# Changelog

All notable changes are documented here. Versions follow Semantic Versioning.

## [Unreleased]

## [0.3.0] - 2026-08-24

### Added

- Added a bounded standard-library JSON observation CLI with stable system,
  GPU, thermal, health, and benchmark profiles.
- Added checksummed evaluation sessions, bounded range summaries, private atomic
  report output, a versioned response schema, and synthetic output example.
- Added a local newline-delimited JSON-RPC STDIO MCP adapter with six read-only
  tools and local, installed, generic-client, and SSH setup guidance.
- Added isolated Prometheus fixtures, privacy/boundary unit tests, and MCP
  transcript tests.

### Changed

- Extended optional system installation and its management command so agent
  observation remains available without `sudo` after deleting the checkout.
- Synchronized application, image, Cargo, citation, and release versions at
  0.3.0. Existing configuration and monitoring databases require no migration.

## [0.2.0] - 2026-08-24

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

[Unreleased]: https://github.com/gracee3/supermicro-observability/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/gracee3/supermicro-observability/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/gracee3/supermicro-observability/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/gracee3/supermicro-observability/releases/tag/v0.1.0
