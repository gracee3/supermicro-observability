# Supermicro observability

Containerized host monitoring with a safe generic core and explicit optional
integrations for NVIDIA GPUs, a selected SMART device, cached fan-controller
metrics, and cAdvisor. The project began on a Supermicro X11SPA-TF workstation,
but committed configuration contains no real disk, GPU, network, fan-header, or
host identity.

## Run from the checkout

This is the default workflow. It does not install a service or copy project
files into system directories. Prerequisites are Docker Engine with Compose,
Python 3, GNU Make, and standard Linux host utilities.

```bash
git clone https://github.com/gracee3/supermicro-observability.git
cd supermicro-observability
make run
```

The first run opens the interactive host configurator, generates a random
Grafana administrator password, and then starts monitoring. Grafana uses the
safe `127.0.0.1:3000` default. The password is printed once and saved at
`runtime/secrets/grafana-admin-password`; both that credential and `.env` are
explicitly ignored by Git.

Use the checkout for routine operation:

```bash
make status
make password
make stop
```

## Agent and evaluation observations

Agents can inspect the running stack through a bounded, predictable JSON CLI.
It queries only the existing loopback Prometheus endpoint and never starts or
stops monitoring:

```bash
scripts/observe status --json
scripts/observe snapshot --profile benchmark --json
scripts/observe summarize --since 10m --profile benchmark --json
scripts/observe begin --label eval-17 --metadata commit=abc123 --json
```

The same standard-library implementation provides a local STDIO MCP server at
`scripts/observe mcp`. System installations expose the no-`sudo` equivalents
`supermicro-observability observe ...` and `supermicro-observability mcp`, even
after the checkout is deleted. No Prometheus port is exposed for remote use;
an MCP client on another trusted machine can launch the installed server over
SSH. See [Agent interface](docs/AGENT-INTERFACE.md) for commands, profiles,
bounds, session completion, privacy behavior, MCP setup, and synthetic output.

Configuration and generated runtime files remain in the checkout, while
Grafana and Prometheus data remain under `data/`. Deleting the checkout also
deletes that local configuration and history unless they are backed up or first
promoted with the optional system installer.

For a trusted directly connected laptop, stop monitoring, bind Grafana to the
host's exact private link address, and start it again:

```bash
make stop
make bind ADDRESS=PRIVATE_HOST_ADDRESS
make run
```

Open `http://PRIVATE_HOST_ADDRESS:3000` and sign in as `admin`. Port `3000` is
Grafana's conventional port; all collector and Prometheus endpoints remain on
host loopback. Restore local-only access while stopped with
`make bind ADDRESS=127.0.0.1`. Run plain `make` to see the short command list.

## Optional system installation

Choose this workflow when the checkout should be disposable or systemd should
own the on-demand lifecycle. Stop checkout-local monitoring, then install:

```bash
make stop
make install-system
```

The first system installation reuses the private checkout configuration,
credential, and any existing Grafana and Prometheus data. If no profile exists,
it opens the same interactive configurator first. Later installations preserve
the installed configuration and data. The installer:

- copies versioned application files to `/opt/supermicro-observability`;
- writes private configuration and the password separately under
  `/etc/supermicro-observability`;
- places persistent Prometheus, Grafana, and runtime state under
  `/var/lib/supermicro-observability`;
- installs the `supermicro-observability` management command in
  `/usr/local/sbin`; and
- installs the systemd unit without starting it and leaves it disabled at boot.

Installation refuses to take over a running checkout stack. After a successful
installation, the password is printed again and remains available at
`/etc/supermicro-observability/grafana-admin-password` or through:

```bash
sudo supermicro-observability password
```

The source checkout may then be deleted. Start and stop the installed stack only
when wanted; it remains disabled across reboots:

```bash
sudo supermicro-observability start
sudo supermicro-observability status
sudo supermicro-observability stop
```

Read-only observation does not require `sudo`:

```bash
supermicro-observability observe snapshot --profile system --json
supermicro-observability mcp
```

For direct-laptop access, set the installed bind while monitoring is stopped:

```bash
sudo supermicro-observability bind PRIVATE_HOST_ADDRESS
sudo supermicro-observability start
```

| Installed path | Purpose | Removal behavior |
|---|---|---|
| `/opt/supermicro-observability` | Versioned application, dashboards, Compose, and scripts | Removed by uninstall |
| `/etc/supermicro-observability` | Root-managed host configuration and Grafana credential | Preserved by uninstall; removed by confirmed purge |
| `/var/lib/supermicro-observability` | Prometheus, Grafana, generated runtime, and build state | Preserved by uninstall; removed by confirmed purge |
| `/usr/local/sbin/supermicro-observability` | Stable lifecycle and maintenance command | Preserved for post-uninstall purge; removed by purge |
| `/etc/systemd/system/supermicro-observability.service` | Disabled-by-default lifecycle unit | Removed by uninstall |

> [!CAUTION]
> Monitoring is portable; physical cooling policy is not. This repository does
> not provide universal fan curves or infer fan-header wiring. Storage devices
> are disabled until a user selects them explicitly. Read [Safety](docs/SAFETY.md)
> before enabling SMART, protected-device rules, or fan integration.

## What is generic and what is local

The committed core provides Prometheus, Grafana, node_exporter, dashboards,
loopback metrics listeners, resource limits, and optional collector profiles. A
private `.env` in checkout-local operation, or
`/etc/supermicro-observability/config.env` after system installation, supplies:

- a non-identifying Prometheus host label;
- enabled NVIDIA and SMART features;
- stable `/dev/disk/by-id/...` storage identities;
- any protected-device and encrypted-root policy;
- the fan textfile directory, if one already exists; and
- a generated node disk-exclusion expression.

The Grafana password is stored in a separate credential file rather than an
environment variable. It uses mode `0600` in the checkout and becomes
root-managed after installation. Generated Prometheus configuration, live
databases, credentials, backups, and build artifacts are not part of Git.

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

Prometheus retains at most 14 days or 12 GB. Grafana and Prometheus use bind
mounts under checkout-local `data/`, or `/var/lib/supermicro-observability`
after installation. Containers have memory, process, CPU-share,
read-only-filesystem, capability and log-rotation constraints.

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

## Source configuration and development

NVIDIA Container Toolkit, `nvidia-smi`, Rust, MUSL, and currently an x86_64 host
are required only when the custom NVIDIA profile is enabled. `configure-host`
previews choices unless `--apply` is supplied. In a source checkout it writes an
ignored `.env` and separate ignored password file atomically with mode `0600`,
resolves whole disks to stable by-id paths, and renders local Prometheus
configuration. The system installer relocates these settings to `/etc`. The
configurator does not mount, unlock, scan, or write a selected device.

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

Grafana binds to `GRAFANA_HTTP_ADDR` from checkout-local `.env` or the installed
`/etc/supermicro-observability/config.env`. It defaults to `127.0.0.1` and
accepts only a loopback or private IP address. With the loopback default, reach
it through an existing trusted SSH connection:

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

## Installed operation

```bash
sudo supermicro-observability start
sudo supermicro-observability stop
sudo supermicro-observability restart
sudo supermicro-observability status
sudo supermicro-observability logs
sudo supermicro-observability configure
```

`start` runs the core plus enabled NVIDIA and SMART profiles. `stop` stops all
monitoring containers. Configuration is accepted only while monitoring is
stopped. None of these commands installs, stops, or restarts a fan controller.

Dashboards use a selectable disk variable instead of a committed device name.
Unavailable optional metrics appear as no data; their empty file-discovery
targets do not create permanent Prometheus scrape failures.

## System removal and fan integration

`make install-system` performs the optional system installation described
above. The conventional `make install` target is an alias. The installer can
also be invoked directly after source configuration with:

```bash
sudo ./scripts/install-system.sh
```

The unit is intentionally not enabled at boot. Reinstallation refuses to modify
an already-running stack. Use the installed management command for lifecycle,
configuration, password retrieval, and logs.

Uninstall stops monitoring, removes its containers, application files, and
systemd unit, but preserves configuration, credentials, and monitoring history:

```bash
sudo supermicro-observability uninstall
```

To additionally delete configuration, credentials, and all stored monitoring
data, use `sudo supermicro-observability purge` and type the required `PURGE`
confirmation. Neither command removes shared container images or touches fan
control.

A separately reviewed controller can
write the documented [fan metrics contract](docs/FAN-METRICS.md). The legacy
X11SPA-TF controller integration is available only through an explicit command
whose confirmation flag states that it restarts fan control. Run this separate
integration from the reviewed source checkout before deleting that checkout:

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
