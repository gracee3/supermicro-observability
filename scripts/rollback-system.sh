#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this rollback with sudo" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
backup_dir=/var/backups/supermicro-observability
service_user="${OBSERVABILITY_USER:-$(stat -c '%U' "$project_dir")}"

systemctl disable --now supermicro-observability.service || true
runuser -u "$service_user" -- docker compose \
    --project-directory "$project_dir" \
    --file "$project_dir/compose.yaml" \
    --profile containers down

if [[ -f "$backup_dir/supermicro-fan-control.pre-metrics" && -f "$backup_dir/supermicro-fan-control.service.pre-metrics" ]]; then
    install -o root -g root -m 0755 "$backup_dir/supermicro-fan-control.pre-metrics" /usr/local/sbin/supermicro-fan-control
    install -o root -g root -m 0644 "$backup_dir/supermicro-fan-control.service.pre-metrics" /etc/systemd/system/supermicro-fan-control.service
    systemctl daemon-reload
    systemctl restart supermicro-fan-control.service
fi

echo "Monitoring containers and startup unit are disabled. Prometheus/Grafana data was preserved."
