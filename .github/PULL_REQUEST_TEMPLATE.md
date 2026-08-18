## What and why

Describe the change, the problem it addresses, and its expected operational
impact.

## Safety and privacy

- [ ] Loopback-only listeners and SSH access assumptions remain intact.
- [ ] Protected-storage and explicit-device guardrails remain intact.
- [ ] Fan control, IPMI cadence, and fail-safe behavior are unchanged, or the
      change includes hardware-specific safety evidence and rollback steps.
- [ ] No secrets, persistent identifiers, workload names, PIDs, or command lines
      are included.

## Evidence

- [ ] `scripts/validate.sh`
- [ ] Relevant Rust tests
- [ ] `scripts/observer-check.sh 300` for collection/performance changes

List the tested hardware/software baseline, repetitions, failed runs, and known
limitations. Disclose copied/generated material and material AI assistance.
