#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this rollback with sudo" >&2
    exit 1
}
[[ "${1:-}" == "--i-understand-this-restarts-fan-control" ]] || {
    echo "usage: sudo $0 --i-understand-this-restarts-fan-control" >&2
    exit 2
}

backup_dir=/var/backups/supermicro-observability
[[ -f "$backup_dir/supermicro-fan-control.pre-metrics" && \
   -f "$backup_dir/supermicro-fan-control.service.pre-metrics" ]] || {
    echo "fixed pre-metrics fan-controller backups are missing" >&2
    exit 1
}

install -o root -g root -m 0755 \
    "$backup_dir/supermicro-fan-control.pre-metrics" \
    /usr/local/sbin/supermicro-fan-control
install -o root -g root -m 0644 \
    "$backup_dir/supermicro-fan-control.service.pre-metrics" \
    /etc/systemd/system/supermicro-fan-control.service
systemctl daemon-reload
systemctl restart supermicro-fan-control.service
systemctl is-active --quiet supermicro-fan-control.service
