# Deployment safety boundaries

## Fan control

The fan controller is deliberately native, independent, and safety-critical.
This repository consumes a cached Prometheus textfile that the controller writes
from its existing IPMI sample. It must not launch a second polling loop or alter
the controller's curves, cadence, header mapping, stop hook, or fail-safe mode.

Before installing fan integration on any host:

1. Physically identify every fan header and direction.
2. Establish safe measured RPM floors and sensor mappings.
3. Review BMC raw commands for the exact board and firmware.
4. Confirm controller stop selects a safe BMC mode.
5. Keep an out-of-band console and rollback path available.

The installer briefly restarts the fan service only when its installed source or
unit differs. During the stop interval the deployed controller selects BMC Full
mode. Do not run the installer unattended on an unverified machine.

## Storage

The target profile assumes:

- `/dev/nvme1n1` is the system disk and sole SMART target; and
- `/dev/nvme0n1` is protected, read-only, and unmounted.

Startup refuses to proceed when the protected device is writable or mounted.
Compose passes only the system disk into `smartctl_exporter`, with scanning
disabled. Verify `lsblk` and `findmnt` live before adapting either identity.
Never use the target configuration as evidence that another host numbers its
devices the same way.

## Remote access and listeners

The stack changes no route, firewall, SSH daemon, or interface. Host networking
is used solely for accurate metrics and every service explicitly binds to
`127.0.0.1`. After changes, verify the listening sockets rather than assuming a
container port declaration supplies isolation.

## Resource limits and rollback

Prometheus is capped at 14 days and 12 GB. Containers have memory, process,
CPU-share, and log-rotation constraints. `monitoring-mode off` leaves the fan
controller untouched. `rollback-system.sh` stops and disables the startup unit,
runs Compose down without deleting project data, and restores the fixed fan
controller backups when present.
