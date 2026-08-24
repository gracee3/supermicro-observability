# Migration from v0.1

Version 0.2 removes host identities and fan-controller lifecycle management from
the committed core. Existing containers keep running until `monitoring-mode` is
invoked; prepare the private profile first.

## 1. Record the existing policy

Using live read-only checks, identify:

- the SMART whole disk, if any;
- every disk that must remain protected;
- whether root is required to come from `/dev/mapper`;
- whether NVIDIA collection is enabled;
- whether real GPU UUIDs, indices, or salted aliases should be published; and
- the existing fan textfile directory, if any.

Do not copy device names from the old Compose file without verifying them.

## 2. Generate and validate the private profile

Example structure only—replace every device with a live-reviewed disk:

```bash
scripts/configure-host --non-interactive --apply \
  --host-label workstation \
  --platform-profile generic \
  --enable-nvidia \
  --gpu-identity-mode alias \
  --smart-device /dev/disk/by-id/REVIEWED-SMART-DISK \
  --protected-device /dev/disk/by-id/REVIEWED-PROTECTED-DISK \
  --require-mapped-root \
  --fan-textfile-dir /var/lib/node_exporter/textfile_collector
scripts/doctor
scripts/validate.sh
```

The configurator preserves the existing Grafana password and resolves whole
disks to stable by-id paths. The protected disk must already be read-only and
unmounted.

## 3. Apply monitoring configuration

```bash
make stop
make install-system
sudo supermicro-observability start
```

The installer copies application files to `/opt`, private configuration and the
Grafana credential to `/etc`, and persistent state to `/var/lib`. The original
checkout is no longer needed afterward. Installation does not start monitoring,
restart fan control, or enable monitoring at boot. Starting may recreate
monitoring containers. Verify loopback listeners, Prometheus targets,
GPU/sample health, SMART scope, fan metric freshness, routes, SSH, and protected
storage afterward.

## Compatibility changes

- Generated Prometheus configuration and file-discovery targets now live under
  ignored `runtime/prometheus/`.
- The custom GPU label `gpu_uuid` is replaced by `gpu_id`. Its value follows
  `GPU_IDENTITY_MODE`; internal rolling state remains UUID-keyed.
- The Grafana folder is named `Host Observability`; dashboard UIDs remain stable.
- SMART uses a stable host by-id path, a fixed container path, and an explicit
  protocol such as `nvme`.
- Core install, rollback, normal, benchmark, and off commands never manage fan
  control. Legacy fan installation and rollback require separate confirmation
  commands.
