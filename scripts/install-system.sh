#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this installer with sudo" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
fan_dir="${FAN_CONTROL_DIR:-$project_dir/../supermicro-fan-control}"
backup_dir=/var/backups/supermicro-observability
fan_restart=0

[[ -f "$fan_dir/supermicro-fan-control" && -f "$fan_dir/supermicro-fan-control.service" ]] || {
    echo "fan controller source not found at $fan_dir; set FAN_CONTROL_DIR to its checkout" >&2
    exit 1
}

service_user="${OBSERVABILITY_USER:-$(stat -c '%U' "$project_dir")}"
getent passwd "$service_user" >/dev/null || {
    echo "observability service user does not exist: $service_user" >&2
    exit 1
}
render_dir="$(mktemp -d)"
trap 'rm -rf -- "$render_dir"' EXIT
"$project_dir/scripts/render-systemd-unit" "$project_dir" "$service_user" >"$render_dir/supermicro-observability.service"

[[ "$(lsblk -dn -o RO /dev/nvme0n1 | tr -d '[:space:]')" == "1" ]]
! findmnt -rn -S /dev/nvme0n1 >/dev/null
[[ -b /dev/nvme1n1 ]]

install -d -o root -g root -m 0750 "$backup_dir"
[[ -e "$backup_dir/supermicro-fan-control.pre-metrics" ]] || \
    cp --preserve=all /usr/local/sbin/supermicro-fan-control "$backup_dir/supermicro-fan-control.pre-metrics"
[[ -e "$backup_dir/supermicro-fan-control.service.pre-metrics" ]] || \
    cp --preserve=all /etc/systemd/system/supermicro-fan-control.service "$backup_dir/supermicro-fan-control.service.pre-metrics"

cmp -s "$fan_dir/supermicro-fan-control" /usr/local/sbin/supermicro-fan-control || fan_restart=1
cmp -s "$fan_dir/supermicro-fan-control.service" /etc/systemd/system/supermicro-fan-control.service || fan_restart=1

install -d -o root -g root -m 0755 /var/lib/node_exporter/textfile_collector
install -o root -g root -m 0755 "$fan_dir/supermicro-fan-control" /usr/local/sbin/supermicro-fan-control
install -o root -g root -m 0644 "$fan_dir/supermicro-fan-control.service" /etc/systemd/system/supermicro-fan-control.service
install -o root -g root -m 0644 "$render_dir/supermicro-observability.service" /etc/systemd/system/supermicro-observability.service

systemd-analyze verify /etc/systemd/system/supermicro-fan-control.service
systemd-analyze verify /etc/systemd/system/supermicro-observability.service
systemctl daemon-reload
systemctl enable supermicro-observability.service

if (( fan_restart )); then
    # The existing stop hook selects BMC Full mode. The controller resumes its
    # unchanged policy immediately after this one brief restart.
    systemctl restart supermicro-fan-control.service
    for _ in {1..30}; do
        systemctl is-active --quiet supermicro-fan-control.service && \
            [[ -s /var/lib/node_exporter/textfile_collector/supermicro_fan.prom ]] && break
        sleep 1
    done
fi
systemctl is-active --quiet supermicro-fan-control.service
[[ -s /var/lib/node_exporter/textfile_collector/supermicro_fan.prom ]]

systemctl start supermicro-observability.service
systemctl is-active --quiet supermicro-observability.service
