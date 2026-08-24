# Deployment safety boundaries

## Fail-closed optional hardware access

The committed defaults enable no NVIDIA runtime, SMART device, protected-device
policy, or external fan metrics. `configure-host` requires explicit selection
and stores persistent device identities only in ignored `.env`. `doctor` checks
the resulting policy before startup.

## Storage

SMART accepts one explicitly selected whole disk and disables automatic scans.
The host path is resolved to `/dev/disk/by-id/...` and mapped read-only to the
fixed container path `/dev/smart-target`. A SMART device must not also be listed
as protected.

Every configured protected disk must be read-only and have no mounted descendant.
It is never passed to a container, and its resolved kernel name is excluded from
node diskstats. The optional mapped-root rule is a host policy, not a universal
assumption.

Before selecting a disk, verify its model, size, topology, mount state, and role
using live read-only tools. The configurator never mounts, unlocks, repairs,
partitions, formats, images, or writes a device.

## Fan control

Monitoring does not validate a cooling policy. The generic stack can consume a
cached [fan metrics contract](FAN-METRICS.md), but normal operation, installation,
rollback, and monitoring modes never manage a controller or poll IPMI.

Fan-control integration requires separate review of the exact board/BMC command
protocol, firmware, physical headers, fan direction, measured RPM floors,
cooling hardware, sensor names, curves, stop hook, and fail-safe behavior. A DMI
platform match does not make fan curves transferable.

The optional legacy integration command requires a confirmation flag that names
its restart behavior. Keep out-of-band console access and an independently
verified safe stop mode before using it.

## Remote access and listeners

The stack changes no route, firewall, SSH daemon, or network interface. Host
networking is used for accurate metrics. Prometheus and every collector bind
explicitly to `127.0.0.1`; Grafana defaults to loopback but may be bound to one
exact private host address for a trusted direct connection. Wildcard and public
Grafana binds are rejected. Verify sockets after deployment rather than assuming
container metadata supplies isolation.

## Resource limits and rollback

Prometheus is capped at 14 days and 12 GB. Containers have memory, process,
CPU-share, and log-rotation constraints. `monitoring-mode off` stops monitoring
only. `rollback-system.sh` disables the monitoring unit and removes containers
without deleting project data or touching fan control.
