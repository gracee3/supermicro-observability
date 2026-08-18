# Research and publication ethics

This is infrastructure software, not a peer-reviewed study. Publications,
papers, reports, and benchmark comparisons built from it should apply the
following practices.

## Accuracy and reproducibility

- Identify the exact commit or release and all modified configuration.
- Separate observed values, derived statistics, and causal interpretations.
- Report failed, negative, and excluded runs with exclusion criteria decided in
  advance where practical.
- Do not generalize this host's fan curves, device mapping, or overhead result to
  different hardware.
- Retain reproducibility metadata. If raw telemetry cannot be shared for privacy
  or security reasons, state that limitation and publish a redacted schema or
  aggregation procedure instead.

## Authorship, attribution, and assistance

Credit only contributors who meet the applicable venue's authorship criteria.
Cite upstream software and prior work; do not treat configuration reuse as
original invention. Preserve license notices and disclose copied or generated
material.

OpenAI Codex assisted with implementation, testing, documentation, and
publication packaging. It is not an author. Human maintainers are accountable
for verifying the code, measurements, citations, safety claims, and licensing.
Future publications should disclose material automated assistance according to
their venue's current policy.

## Privacy and data minimization

The default stack avoids per-process GPU metrics, PID and command-line labels,
external telemetry, and non-loopback listeners. Prometheus ingestion also drops
upstream disk serial and broad NVML UUID/serial/PCI labels. Published screenshots and data
must be checked for usernames, hostnames, IP addresses, GPU UUIDs, filesystem
paths, Grafana credentials, workload names, and other identifying metadata.
Obtain appropriate consent before collecting or publishing metrics about other
people's workloads.

## Safety and dual use

Monitoring does not validate a cooling policy. Do not imply that observed fan
speeds prove thermal safety, and do not deploy the target host's controller
settings on uncalibrated hardware. Security findings that could endanger storage
or cooling should be disclosed privately under `SECURITY.md`.

## Declarations and corrections

The repository does not infer or declare a maintainer's funding, employment
interests, or conflicts. Each publication must provide accurate funding,
conflict-of-interest, ethics-review, data-availability, and author-contribution
statements required by its venue. Correct material errors promptly through a
documented commit, changelog entry, and release note; do not silently rewrite a
published result.
