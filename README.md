# Supermicro observability

Loopback-only, containerized monitoring for a Supermicro X11SPA-TF workstation
with two NVIDIA RTX 3090 GPUs. The stack combines Prometheus, Grafana,
node_exporter, a persistent 250 ms GPU sampler, a slower NVML catalog, narrowly
scoped SMART collection, and cached metrics from an existing native fan
controller.

> [!CAUTION]
> This repository encodes one machine's storage identities, fan-controller
> integration, and measured safety assumptions. Read [Safety](docs/SAFETY.md)
> and verify every device and fan mapping before deploying it elsewhere. The
> configuration is not a universal Supermicro fan profile.

## Design guarantees

- Every HTTP listener binds to `127.0.0.1`; Grafana is intended to be reached
  through SSH port forwarding.
- No route, firewall, SSH, or network-interface changes are made.
- The protected NVMe device is checked for read-only/unmounted state before
  startup and is never passed to a container.
- The native fan controller remains outside Docker. Monitoring consumes its
  cached textfile output and does not add IPMI polling.
- GPU process IDs, command lines, and other per-process metrics are disabled.
- Prometheus retention is capped at 14 days and 12 GB.

The live target was checked on 2026-08-17: `/dev/nvme1n1` is the encrypted
system disk and the only SMART target; `/dev/nvme0n1` is a protected,
unmounted, read-only secondary disk. These names must not be copied to another
host without live verification.

## Quick start

Prerequisites are Docker Engine with Compose, the NVIDIA Container Toolkit, a
working `nvidia-smi`, Rust with the `x86_64-unknown-linux-musl` target, and the
host utilities used by the validation scripts. The external fan controller is
required only for native fan-metric installation.

```bash
git clone git@github.com:gracee3/supermicro-observability.git
cd supermicro-observability
scripts/validate.sh
scripts/monitoring-mode normal
```

The first `normal` start creates `.env` atomically with mode `0600` and a random
Grafana administrator password. Never commit that file. See `.env.example` for
the variable names, not deployable credentials.

To reach Grafana from a trusted client:

```bash
ssh -L 3000:127.0.0.1:3000 USER@MONITORING_HOST
```

Then open `http://127.0.0.1:3000`.

## Endpoints

| Service | Loopback endpoint | Collection interval |
|---|---:|---:|
| Grafana | `127.0.0.1:3000` | 1 s dashboard refresh |
| Prometheus | `127.0.0.1:9090` | varies by job |
| node_exporter | `127.0.0.1:9100` | 1 s fast / 15 s slow |
| NVML catalog/XID exporter | `127.0.0.1:9835` | 15 s, continuous XID watcher |
| custom persistent GPU sampler | `127.0.0.1:9836` | 250 ms sample / 500 ms scrape |
| SMART exporter | `127.0.0.1:9633` | 5 min |
| optional cAdvisor | `127.0.0.1:8080` | 5 s |

Custom metrics use the stable `supermicro_gpu_*` and `supermicro_fan_*`
prefixes. cAdvisor is disabled unless explicitly enabled.

## Operating modes

```bash
scripts/monitoring-mode normal
scripts/monitoring-mode benchmark
scripts/monitoring-mode off
scripts/container-metrics on
scripts/container-metrics off
```

`normal` runs the six core containers. `benchmark` retains Prometheus,
node_exporter, the fast GPU sampler, and cached fan metrics while stopping
Grafana, SMART, the slower NVML catalog, and cAdvisor. `off` stops monitoring
containers and does not touch the fan controller.

Prometheus and Grafana data remain under `data/` and are excluded from Git.
Backups, Rust build products, and `.env` are also excluded.

## Native installation and rollback

The native fan controller is a separate safety-critical project and is not
vendored here. By default the installer expects a sibling checkout named
`supermicro-fan-control`; set `FAN_CONTROL_DIR` to use another location. It must
provide `supermicro-fan-control` and `supermicro-fan-control.service`, already
reviewed and calibrated for the host.

```bash
sudo ./scripts/install-system.sh
```

The installer preserves fixed pre-metrics backups under
`/var/backups/supermicro-observability`, installs the fan metrics integration,
briefly restarts only the fan service if its files changed, renders the systemd
unit for the project owner, and enables the Compose oneshot. The controller's
stop hook selects BMC Full mode until the controller resumes.

Rollback stops and disables the monitoring unit without deleting bind-mounted
data, then restores the pre-metrics fan controller if backups exist:

```bash
sudo ./scripts/rollback-system.sh
```

## Validation and measured overhead

`scripts/validate.sh` checks Compose, Prometheus, dashboard JSON, Rust tests and
lint, shell syntax, image digests, systemd rendering, and storage-device scope.
`scripts/observer-check.sh 300` checks the five-minute CPU and memory budgets and
reports down Prometheus targets.

A single target-host run on 2026-08-17 observed:

- fast GPU exporter: 1.885% of one logical CPU on average;
- complete stack: 8.498% of one logical CPU on average;
- peak aggregate container memory: 285.8 MiB;
- node fast-scrape p95: 21.4 ms; GPU scrape p95: 1.78 ms; and
- Prometheus data growth over a 30-second observation: approximately 6.9 KiB/s.

These are descriptive engineering measurements, not general performance
claims. The procedure, limitations, and reproduction steps are in
[Methodology](docs/METHODOLOGY.md).

## Publication and reuse

- Cite the software using [`CITATION.cff`](CITATION.cff).
- Review [publication ethics](docs/PUBLICATION-ETHICS.md) before reporting or
  extending benchmark results.
- Contributions must follow [`CONTRIBUTING.md`](CONTRIBUTING.md), including
  provenance and test disclosures.
- Upstream components and their independent licensing are listed in
  [`THIRD_PARTY.md`](THIRD_PARTY.md).

This repository is licensed under the [MIT License](LICENSE). Container images
and external projects retain their own licenses and trademarks.
