#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this installer with sudo" >&2
    exit 1
}
[[ "${1:-}" == "--i-understand-this-restarts-fan-control" ]] || {
    echo "usage: sudo FAN_CONTROL_DIR=/path $0 --i-understand-this-restarts-fan-control" >&2
    exit 2
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
fan_dir="${FAN_CONTROL_DIR:-$project_dir/../supermicro-fan-control}"
backup_dir=/var/backups/supermicro-observability

[[ -f "$fan_dir/supermicro-fan-control" && -f "$fan_dir/supermicro-fan-control.service" ]] || {
    echo "reviewed fan-controller source not found at $fan_dir" >&2
    exit 1
}
python3 "$project_dir/scripts/host_config.py" check --quiet --no-compose
profile="$(sed -n 's/^PLATFORM_PROFILE=//p' "$project_dir/.env")"
fan_mode="$(sed -n 's/^FAN_METRICS_MODE=//p' "$project_dir/.env")"
textfile_dir="$(sed -n 's/^TEXTFILE_COLLECTOR_DIR=//p' "$project_dir/.env")"
[[ "$profile" == "supermicro-x11spa-tf" ]] || {
    echo "legacy fan integration requires PLATFORM_PROFILE=supermicro-x11spa-tf" >&2
    exit 1
}
[[ "$fan_mode" == "textfile" && "$textfile_dir" == "/var/lib/node_exporter/textfile_collector" ]] || {
    echo "configure the system fan textfile directory before installing this integration" >&2
    exit 1
}

install -d -o root -g root -m 0750 "$backup_dir"
[[ -e "$backup_dir/supermicro-fan-control.pre-metrics" ]] || \
    cp --preserve=all /usr/local/sbin/supermicro-fan-control "$backup_dir/supermicro-fan-control.pre-metrics"
[[ -e "$backup_dir/supermicro-fan-control.service.pre-metrics" ]] || \
    cp --preserve=all /etc/systemd/system/supermicro-fan-control.service "$backup_dir/supermicro-fan-control.service.pre-metrics"

install -d -o root -g root -m 0755 /var/lib/node_exporter/textfile_collector
install -o root -g root -m 0755 "$fan_dir/supermicro-fan-control" /usr/local/sbin/supermicro-fan-control
install -o root -g root -m 0644 "$fan_dir/supermicro-fan-control.service" /etc/systemd/system/supermicro-fan-control.service
systemd-analyze verify /etc/systemd/system/supermicro-fan-control.service
systemctl daemon-reload

# The reviewed controller stop hook must select its safe BMC mode. This is the
# only command in the observability repository that restarts fan control.
systemctl restart supermicro-fan-control.service
for _ in {1..30}; do
    systemctl is-active --quiet supermicro-fan-control.service && \
        [[ -s /var/lib/node_exporter/textfile_collector/supermicro_fan.prom ]] && exit 0
    sleep 1
done
echo "fan integration did not become healthy within 30 seconds" >&2
exit 1
