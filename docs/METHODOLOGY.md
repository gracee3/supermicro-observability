# Measurement and reproducibility methodology

## Scope

The reported measurements describe one Supermicro X11SPA-TF host with an Intel
Xeon Silver 4215R, 96 GB nominal RAM, two GeForce RTX 3090 GPUs, NVIDIA driver
610.43.02, and Docker Engine 29.7.2. The host baseline and measurements were
checked on 2026-08-17. They are engineering observations, not estimates for a
population of systems.

The monitoring design intentionally excludes process-level GPU metrics,
Alertmanager, Intel PCM, eBPF probes, and cAdvisor by default. Exclusions reduce
observer effects and limit collection of potentially identifying workload data.

## Collection design

- The custom exporter holds one persistent `nvidia-smi --loop-ms=250` process.
  It publishes the latest sample and one-second min/max/mean aggregates for
  selected metrics. Prometheus scrapes it every 500 ms.
- node_exporter is separated logically into a 1 s fast scrape and a 15 s slow
  scrape by using per-scrape collector parameters against one listener.
- The broader NVML exporter is collected every 15 s. SMART is collected every
  5 minutes from one explicitly named device.
- Fan metrics are written atomically by the existing controller from the IPMI
  sample it already collected. The monitoring stack performs no additional IPMI
  query.
- Prometheus and Grafana store data only in project-local bind mounts.

The Rust test suite covers normal and unavailable fields, malformed input,
dual-GPU ordering, restart behavior, and stale-data semantics. Run all static
checks with:

```bash
scripts/validate.sh
```

## Observer-effect check

The five-minute acceptance check is:

```bash
scripts/monitoring-mode normal
scripts/observer-check.sh 300
```

Every five seconds, the script samples `docker stats` for the running project
containers. It reports arithmetic mean CPU percentages and the maximum summed
memory usage. CPU percentage is expressed as a fraction of one logical CPU, as
reported by Docker. The acceptance thresholds are:

- custom fast GPU exporter average below 2% of one logical CPU;
- complete normal-mode stack average below 10% of one logical CPU; and
- aggregate monitoring memory below 1 GiB.

After sampling, the script queries Prometheus for targets where `up == 0`.
Scrape-duration percentiles are derived from Prometheus's own scrape metrics.
Short-window storage growth is the difference in the Prometheus data-directory
size over the observation interval.

## Reported target-host result

The 2026-08-17 run reported 1.885% fast-exporter CPU, 8.498% complete-stack CPU,
and 285.8 MiB peak aggregate memory. Observed p95 scrape durations were 21.4 ms
for the fast node job and 1.78 ms for the custom GPU endpoint. Prometheus data
grew by approximately 6.9 KiB/s during a separate 30-second check.

## Limitations

- The repository records summary results, not raw high-frequency host telemetry,
  because raw data could reveal workloads and persistent hardware identifiers.
- The published result is one run, without confidence intervals or randomized
  workload order. It must not be represented as a comparative benchmark.
- `docker stats` and Prometheus measurements have their own overhead and timing
  error. They are adequate for a deployment budget, not precision power or
  microarchitectural analysis.
- Ambient conditions, fan state, GPU clocks, background activity, driver
  versions, and container caches can change results.
- A 30-second write-rate observation cannot predict long-term TSDB compaction
  behavior; the configured 12 GB limit is the controlling safety bound.

## Reporting extensions

Report the exact commit, image digests, kernel/driver versions, hardware,
collection mode, duration, sample count, aggregation, unsuccessful runs, and
configuration changes. Distinguish measurements from interpretations. Do not
discard results solely because they contradict an expected performance claim.
