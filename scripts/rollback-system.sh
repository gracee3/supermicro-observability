#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this rollback with sudo" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
service_user="${OBSERVABILITY_USER:-$(stat -c '%U' "$project_dir")}"

systemctl disable --now supermicro-observability.service || true
runuser -u "$service_user" -- docker compose \
    --project-directory "$project_dir" \
    --file "$project_dir/compose.yaml" \
    --profile nvidia \
    --profile smart \
    --profile containers \
    down

echo "Monitoring containers and startup unit are disabled. Data was preserved; fan control was untouched."
