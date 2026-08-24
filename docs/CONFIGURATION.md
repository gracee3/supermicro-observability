# Host configuration

`scripts/configure-host` is the supported interface for host-specific settings.
It reads and replaces the ignored `.env` atomically, preserves or generates the
Grafana secret, and renders ignored runtime files under `runtime/`. Do not copy a
different machine's `.env`.

Grafana defaults to `127.0.0.1:3000`. Interactive configuration can select an
exact private host address for a trusted directly connected client. Wildcard and
public binds are rejected; Prometheus and every collector remain loopback-only.

## Safe generic profile

```bash
scripts/configure-host --non-interactive --apply \
  --host-label workstation \
  --platform-profile generic \
  --disable-nvidia \
  --disable-smart \
  --clear-protected-devices \
  --allow-any-root \
  --disable-fan-metrics
scripts/doctor
```

This starts only Prometheus, Grafana, and node_exporter. SMART and NVIDIA targets
remain empty rather than failing continuously.

## NVIDIA profile

```bash
scripts/configure-host --non-interactive --apply --enable-nvidia
scripts/doctor
```

The doctor requires `nvidia-smi` to discover at least one GPU. UUIDs and GPU
count are read dynamically; UUIDs are not stored in `.env`. Rolling state is
always keyed internally by UUID. Published metric identity is configurable:

```bash
scripts/configure-host --non-interactive --apply \
  --enable-nvidia \
  --gpu-identity-mode alias
```

`alias` is the privacy-preserving default and derives a stable pseudonymous
`gpu_id` from the UUID and a random local salt stored in `.env`. `index` exposes
only the current NVIDIA index and may change after hardware reordering. `uuid`
publishes the real UUID as `gpu_id` for environments that require direct
hardware correlation. Salted aliases are pseudonyms, not a cryptographic
anonymity guarantee.

The slower upstream NVML endpoint can expose UUID, serial, and PCI identifiers.
It remains loopback-only, and Prometheus drops those identifier labels before
storage. The custom `gpu_id` is the supported identity for dashboards and
published metric exports.

NVIDIA metrics may return `N/A` for model-specific fields. An unsupported query
field or incompatible driver is reported by sampler health and bounded restart
metrics.

## SMART device

Select exactly one whole disk. Automatic device scanning remains disabled:

```bash
scripts/configure-host --non-interactive --apply \
  --smart-device /dev/disk/by-id/REVIEWED-WHOLE-DISK-ID
scripts/doctor
```

If a kernel name such as `/dev/nvme1n1` is supplied, the configurator resolves it
to a stable by-id symlink before writing `.env`. It rejects partitions and, by
default, rejects devices with no stable by-id identity. Compose maps the selected
host disk read-only to the fixed container name `/dev/smart-target`. Because
that neutral name removes kernel-name protocol hints, the configurator records
an explicit `nvme` device type for NVMe disks. Other transports default to
`auto`; override a reviewed controller type when necessary:

```bash
scripts/configure-host --non-interactive --apply \
  --smart-device /dev/disk/by-id/REVIEWED-WHOLE-DISK-ID \
  --smart-device-type sat
```

Disable SMART with `--disable-smart`.

## Protected devices and root policy

Each `--protected-device` flag selects a whole disk that must remain read-only
and have no mounted descendant:

```bash
scripts/configure-host --non-interactive --apply \
  --protected-device /dev/disk/by-id/REVIEWED-PROTECTED-DISK \
  --require-mapped-root
```

Protected devices are never passed into a container. Their resolved kernel names
are added to node_exporter's diskstats exclusion, and their node NVMe sysfs
series are dropped at Prometheus ingestion. Disk serial labels from node and
SMART exporters are also removed before storage. `doctor` refuses startup if a
protected disk is writable or any descendant is mounted. `--require-mapped-root`
also requires `/` to come from `/dev/mapper/...`; use `--allow-any-root` when that
policy does not describe the host.

Clear the list with `--clear-protected-devices`. Device selection never mounts,
unlocks, repairs, scans, or writes a disk.

## Fan textfile metrics

Monitoring can consume an existing controller's cached metrics without managing
the controller:

```bash
scripts/configure-host --non-interactive --apply \
  --fan-textfile-dir /var/lib/node_exporter/textfile_collector
```

The directory is mounted read-only into node_exporter. Disable the integration
with `--disable-fan-metrics`; an empty project-local directory is used instead.
See [Fan metrics](FAN-METRICS.md) for the metric contract.

## Platform profiles

`generic` makes no motherboard assertion. `supermicro-x11spa-tf` requires the
live DMI baseboard product name to contain `X11SPA-TF`. The platform profile is
a compatibility assertion only: it does not install a controller, issue IPMI
commands, or supply curves.

## Preview, inspection, and recovery

Omit `--apply` to preview a profile. Secrets and device identities are redacted
unless `--show-sensitive` is explicitly supplied:

```bash
scripts/configure-host --non-interactive --enable-nvidia
```

Run `scripts/doctor` after every change. If generated Prometheus configuration
is stale, rerun the last `configure-host --apply` command. `.env` must remain
mode `0600`.
