# Supermicro observability

Containerized host monitoring with a safe generic core and explicit optional
integrations for NVIDIA GPUs, a selected SMART device, cached fan-controller
metrics, and cAdvisor. The project began on a Supermicro X11SPA-TF workstation,
but committed configuration contains no real disk, GPU, network, fan-header, or
host identity.

## Install and run on demand

Prerequisites are Docker Engine with Compose, Python 3, GNU Make, and standard
Linux host utilities. Clone the repository and run the interactive installer:

```bash
git clone git@github.com:gracee3/supermicro-observability.git
cd supermicro-observability
make install
```

The installer asks which optional collectors and host safety policies to use.
For Grafana, keep `127.0.0.1` for SSH-tunnel-only access or enter the host's
private address on a trusted direct link. It then:

- generates a random Grafana administrator password;
- writes the private host profile to the ignored `.env` file;
- prints the password in the terminal and saves it to the explicitly ignored
  `runtime/secrets/grafana-admin-password` file with mode `0600`; and
- installs the systemd unit without starting it and leaves it disabled at boot.

The terminal display may remain in shell or tmux scrollback. Retrieve the saved
password later with `make password`.

Start and stop monitoring only when wanted:

```bash
make start
make status
make stop
```

From a directly connected laptop, open `http://MONITORING_HOST:3000` and sign in
as `admin` with the generated password. `MONITORING_HOST` is the private address
entered during installation. Port `3000` is Grafana's conventional port; all
collector and Prometheus endpoints remain bound to host loopback.

> [!CAUTION]
> Monitoring is portable; physical cooling policy is not. This repository does
> not provide universal fan curves or infer fan-header wiring. Storage devices
> are disabled until a user selects them explicitly. Read [Safety](docs/SAFETY.md)
> before enabling SMART, protected-device rules, or fan integration.

## What is generic and what is local

The committed core provides Prometheus, Grafana, node_exporter, dashboards,
loopback listeners, resource limits, and optional collector profiles. A private
`.env` generated on each host supplies:

- a non-identifying Prometheus host label;
- enabled NVIDIA and SMART features;
- stable `/dev/disk/by-id/...` storage identities;
- any protected-device and encrypted-root policy;
- the fan textfile directory, if one already exists; and
- a generated node disk-exclusion expression.

`.env`, generated Prometheus configuration/targets, live databases, backups,
and build artifacts are excluded from Git.

The `supermicro-x11spa-tf` platform profile performs a DMI compatibility check.
It does not provide or change fan curves. A dated, redacted example deployment
is documented separately in
[the X11SPA-TF dual-GPU case study](docs/deployments/x11spa-tf-dual-rtx3090.md).

## Technical architecture

Docker Compose runs the services with host networking so host metrics remain
accurate. Only Grafana may be bound to a configured private host address. The
data plane stays on `127.0.0.1`: exporters expose local metrics, Prometheus
scrapes and stores them, and Grafana queries Prometheus through its provisioned
datasource.

| What is observed | Collector | How it is collected | Default cadence |
|---|---|---|---:|
| CPU, memory, pressure, filesystems, disks, network, thermals, hwmon and EDAC | node_exporter | Split fast and slow Prometheus scrapes against a least-collector listener | 1 s / 15 s |
| GPU utilization, clocks, power, temperature and rolling aggregates | custom Rust GPU exporter | One persistent `nvidia-smi --loop-ms=250` sampler keyed internally by GPU UUID | 250 ms sample / 500 ms scrape |
| Broader GPU inventory, health and XID data | NVIDIA NVML exporter | NVML collector with identifying labels dropped before Prometheus storage | 15 s |
| One explicitly selected whole disk | SMART exporter | Read-only mapping to a neutral container device; automatic scanning disabled | 5 min |
| Existing fan-controller telemetry | node_exporter textfile collector | Reads a cached metrics file; never polls IPMI or controls fans | Producer-defined |
| Container resource use | cAdvisor | Explicit opt-in with process, labels and high-cardinality metrics constrained | 5 s |
| Monitoring health and overhead | Prometheus and provisioned dashboards | Target health, scrape timing and stack resource dashboards | Dashboard-dependent |

Prometheus retains at most 14 days or 12 GB. Grafana and Prometheus use ignored
project-local bind mounts for persistent data. Containers have memory, process,
CPU-share, read-only-filesystem, capability and log-rotation constraints.

```text
host sensors and kernel interfaces
        │
        ├── node_exporter ────────────┐
        ├── custom/NVML GPU exporters ┤
        ├── optional SMART exporter ──┼──> Prometheus ──> Grafana :3000
        ├── optional fan textfile ─────┤       127.0.0.1
        └── optional cAdvisor ─────────┘
```

No process IDs, command lines, or per-process GPU metrics are collected. GPU
identity defaults to a stable salted alias. Disabled optional collectors use
empty file-discovery targets rather than producing permanent scrape failures.

## Explicit non-interactive configuration

NVIDIA Container Toolkit, `nvidia-smi`, Rust, MUSL, and currently an x86_64 host
are required only when the custom NVIDIA profile is enabled. `configure-host`
previews choices unless `--apply` is supplied. It writes `.env`
atomically with mode `0600`, generates a random Grafana password, resolves whole
disks to stable by-id paths, and renders local Prometheus configuration. It does
not mount, unlock, scan, or write a selected device.

For repeatable/headless setup, use explicit flags. This safe generic example
enables no optional hardware access:

```bash
scripts/configure-host --non-interactive --apply \
  --host-label workstation \
  --platform-profile generic \
  --disable-nvidia \
  --disable-smart \
  --clear-protected-devices \
  --allow-any-root \
  --disable-fan-metrics
```

See [Configuration](docs/CONFIGURATION.md) for NVIDIA, SMART, protected-device,
and fan-textfile examples. Existing v0.1 deployments should follow the
[v0.2 migration guide](docs/MIGRATION-v0.2.md) before restarting containers.

## Access and endpoints

Grafana binds to `GRAFANA_HTTP_ADDR`, which defaults to `127.0.0.1` and accepts
only a loopback or private IP address. With the loopback default, reach it
through an existing trusted SSH connection:

```bash
ssh -L 3000:127.0.0.1:3000 USER@MONITORING_HOST
```

Then open `http://127.0.0.1:3000`.

| Service | Host endpoint | Collection interval | Feature |
|---|---:|---:|---|
| Grafana | `${GRAFANA_HTTP_ADDR}:3000` | 1 s dashboard refresh | core |
| Prometheus | `127.0.0.1:9090` | varies by job | core |
| node_exporter | `127.0.0.1:9100` | 1 s fast / 15 s slow | core |
| persistent GPU sampler | `127.0.0.1:9836` | 250 ms sample / 500 ms scrape | NVIDIA |
| NVML catalog/XID exporter | `127.0.0.1:9835` | 15 s | NVIDIA |
| SMART exporter | `127.0.0.1:9633` | 5 min | SMART |
| cAdvisor | `127.0.0.1:8080` | 5 s | explicit opt-in |

GPU UUIDs are discovered at runtime and are not configuration inputs. The
exporter always stores rolling state by UUID, so index reordering does not merge
physical devices. Published `gpu_id` labels can use the real UUID, current index,
or the default stable salted alias; the choice and alias salt are private host
configuration. No process IDs, command lines, or per-process GPU metrics are
collected.

## Operation

```bash
scripts/monitoring-mode normal
scripts/monitoring-mode benchmark
scripts/monitoring-mode off
scripts/container-metrics on
scripts/container-metrics off
```

`normal` starts the core plus enabled NVIDIA and SMART profiles. `benchmark`
keeps Prometheus, node_exporter, and the fast GPU sampler when configured, while
stopping Grafana, SMART, the slow NVML catalog, and cAdvisor. `off` stops all
monitoring containers. None of these commands installs, stops, or restarts a fan
controller.

Dashboards use a selectable disk variable instead of a committed device name.
Unavailable optional metrics appear as no data; their empty file-discovery
targets do not create permanent Prometheus scrape failures.

## Native startup and fan integration

`make install` installs the monitoring systemd unit disabled at boot and does
not start it. It can also be installed directly after host configuration with:

```bash
sudo ./scripts/install-system.sh
```

The unit is intentionally not enabled at boot. Reinstalling does not stop an
already-running stack. Use `make start` and `make stop`, or the equivalent
`sudo systemctl start|stop supermicro-observability` commands.

Rollback disables the unit and removes containers without deleting bind-mounted
data:

```bash
sudo ./scripts/rollback-system.sh
```

Both commands leave fan control untouched. A separately reviewed controller can
write the documented [fan metrics contract](docs/FAN-METRICS.md). The legacy
X11SPA-TF controller integration is available only through an explicit command
whose confirmation flag states that it restarts fan control:

```bash
sudo FAN_CONTROL_DIR=/reviewed/path \
  ./scripts/install-fan-integration.sh \
  --i-understand-this-restarts-fan-control
```

## Validation and publication

`scripts/doctor` validates only the private host profile and live prerequisites.
`scripts/validate.sh` checks generated configuration, Compose, Prometheus,
dashboards, Python configuration tests, Rust tests/lint, shell syntax, systemd,
image digests, optional target wiring, and the absence of committed device
identities.

`scripts/observer-check.sh 300` measures the deployment budget. Its method and
limitations are in [Methodology](docs/METHODOLOGY.md); results from one machine
must not be presented as general performance claims.

- Cite releases using [`CITATION.cff`](CITATION.cff).
- Follow [publication ethics](docs/PUBLICATION-ETHICS.md) for derived reports.
- Follow [`CONTRIBUTING.md`](CONTRIBUTING.md) for provenance and testing.
- Review [`THIRD_PARTY.md`](THIRD_PARTY.md) for upstream components.

The project is licensed under the [MIT License](LICENSE). Container images and
external controllers retain their independent licenses and trademarks.
