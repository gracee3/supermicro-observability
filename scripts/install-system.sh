#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this installer with sudo" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
service_user="${OBSERVABILITY_USER:-$(stat -c '%U' "$project_dir")}"

getent passwd "$service_user" >/dev/null || {
    echo "observability service user does not exist: $service_user" >&2
    exit 1
}

runuser -u "$service_user" -- "$project_dir/scripts/doctor" --quiet

render_dir="$(mktemp -d)"
trap 'rm -rf -- "$render_dir"' EXIT
"$project_dir/scripts/render-systemd-unit" "$project_dir" "$service_user" >"$render_dir/supermicro-observability.service"

install -o root -g root -m 0644 \
    "$render_dir/supermicro-observability.service" \
    /etc/systemd/system/supermicro-observability.service
systemd-analyze verify /etc/systemd/system/supermicro-observability.service
systemctl daemon-reload
systemctl enable supermicro-observability.service
systemctl start supermicro-observability.service
systemctl is-active --quiet supermicro-observability.service

echo "Monitoring startup installed. Fan-controller files and services were not modified."
