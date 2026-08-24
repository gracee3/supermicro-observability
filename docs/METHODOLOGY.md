# Measurement and reproducibility methodology

## Scope

This repository provides an engineering measurement procedure, not a comparative
benchmark. Hardware-specific results belong in dated deployment reports under
`docs/deployments/` with identifiers redacted where necessary.

The default design excludes process-level GPU metrics, Alertmanager, Intel PCM,
eBPF probes, and cAdvisor. Optional features must be reported when enabled.

## Collection design

- The custom NVIDIA exporter holds one persistent
  `nvidia-smi --loop-ms=250` process. It publishes latest samples and one-second
  min/max/mean aggregates. Prometheus scrapes it every 500 ms.
- node_exporter has a 1 s fast scrape and a 15 s slow scrape through per-scrape
  collector parameters against one listener.
- The broader NVML exporter is collected every 15 s. SMART is collected every
  5 minutes from one explicitly selected device.
- Fan metrics, when enabled, come from an existing controller's cached textfile.
  Monitoring performs no additional IPMI query.
- Prometheus and Grafana store data only in dedicated bind mounts beneath local
  `data/`, or `/var/lib/supermicro-observability` after system installation.

## Reproduction metadata

Record the exact commit or release, image digests, host profile feature flags,
kernel, NVIDIA driver, Docker version, hardware, ambient conditions, workload,
duration, sample count, aggregation, and all unsuccessful or excluded runs. Do
not publish private configuration, storage identities, GPU UUIDs, usernames, or raw workload
labels.

Run the configuration and static checks first:

```bash
scripts/doctor
scripts/validate.sh
```

## Observer-effect check

The five-minute deployment-budget check is:

```bash
scripts/monitoring-mode normal
scripts/observer-check.sh 300
```

Every five seconds, the script samples `docker stats` for this Compose project.
It reports arithmetic mean CPU percentages and maximum summed memory usage. CPU
percentage is a fraction of one logical CPU as reported by Docker. The default
acceptance thresholds are:

- fast GPU exporter average below 2% of one logical CPU when enabled;
- complete normal-mode stack average below 10% of one logical CPU; and
- aggregate monitoring memory below 1 GiB.

The GPU threshold is skipped conceptually when NVIDIA is disabled, although the
script reports zero. After sampling, the script queries Prometheus for targets
where `up == 0`. Optional jobs with empty file-discovery targets do not count as
failed targets.

## Limitations

- `docker stats` and Prometheus add overhead and timing error. This is a
  deployment budget, not precision power or microarchitectural analysis.
- Short storage observations cannot predict TSDB compaction; the 12 GB retention
  bound controls long-term space.
- Ambient conditions, fan state, GPU clocks, caches, drivers, and background
  activity can materially alter results.
- A single run has no confidence interval and must not be generalized.
- Raw high-frequency telemetry may reveal workloads and persistent hardware
  identities; state any privacy-based data-availability limitation explicitly.
