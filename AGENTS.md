# Contributor and agent guidance

This repository provides loopback-only host observability with explicit generic
configuration and optional NVIDIA, SMART, fan-metric, and cAdvisor integrations.
It observes; it does not define universal hardware policy, infer device roles,
or manage normal fan control.

Before changing implementation, read `README.md`, `CONTRIBUTING.md`,
`docs/SAFETY.md`, `docs/CONFIGURATION.md`, and `docs/METHODOLOGY.md`. Read the
migration, fan-metrics, deployment, and publication documents when those
surfaces are affected.

## Validation boundary

No host-independent ordinary check has yet been approved. For instruction-only
changes, run:

```bash
git diff --check
```

Do not run `scripts/validate.sh`, Docker or Compose, live host probes, NVIDIA or
SMART access, service installation, fan integration, or observer benchmarks
without separately reviewing their exact effects and authorization.

## Safety, privacy, and delivery

- Never commit credentials, `.env`, host or device identities, GPU UUIDs,
  serials, addresses, live databases, process details, raw host captures, or
  unbounded metric labels. Examples must be visibly synthetic.
- Preserve loopback listeners, fail-closed optional collectors, stable explicit
  device selection, protected-device exclusion, resource bounds, and separation
  from fan control. Never generalize a curve or device assumption from one host.
- Keep generated configuration, dashboards, Compose, migrations, third-party
  notices, measurement limits, and source provenance aligned.
- Use a focused feature branch and sign off commits as required by
  `CONTRIBUTING.md`. Push the validated change and open a pull request;
  host-configuration or dependency changes must not auto-merge.
- After publication, send the exact commit, PR, validation, outcome, risks, and
  next action to the repository's external coordination record. Do not claim
  completion until that remote handoff is verified.
