#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
config_file="${OBSERVABILITY_CONFIG_FILE:-$project_dir/.env}"
runtime_dir="${OBSERVABILITY_RUNTIME_DIR:-$project_dir/runtime}"
compose=(docker compose --env-file "$config_file" --project-directory "$project_dir" --file "$project_dir/compose.yaml")

"$project_dir/scripts/doctor" --quiet
"${compose[@]}" --profile nvidia --profile smart --profile containers config --quiet

docker run --rm \
    --entrypoint /bin/promtool \
    -v "$runtime_dir/prometheus:/etc/prometheus:ro" \
    prom/prometheus:v3.13.2-distroless@sha256:64f71bb84e03c855948418b0fc5dea53e9543d8e3fc9931598f583805507f05e \
    check config /etc/prometheus/prometheus.yml

for target in "$runtime_dir"/prometheus/file_sd/*.json; do
    python3 -m json.tool "$target" >/dev/null
done
for dashboard in "$project_dir"/grafana/dashboards/*.json; do
    python3 -m json.tool "$dashboard" >/dev/null
done
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
    "$project_dir/scripts/generate-dashboards.py"
python3 -m py_compile "$project_dir/scripts/host_config.py"
python3 -m unittest discover -s "$project_dir/tests" -v

cargo fmt --manifest-path "$project_dir/gpu-exporter/Cargo.toml" -- --check
cargo test --locked --quiet --manifest-path "$project_dir/gpu-exporter/Cargo.toml"
cargo clippy --locked --quiet --manifest-path "$project_dir/gpu-exporter/Cargo.toml" --all-targets -- -D warnings

for script in \
    monitoring-mode \
    container-metrics \
    observer-check.sh \
    source-control \
    configure-host \
    doctor \
    install-system.sh \
    rollback-system.sh \
    install-fan-integration.sh \
    rollback-fan-integration.sh \
    render-systemd-unit \
    render-management-command \
    supermicro-observability.in; do
    bash -n "$project_dir/scripts/$script"
done

render_dir="$(mktemp -d)"
trap 'rm -rf -- "$render_dir"' EXIT
"$project_dir/scripts/render-systemd-unit" "$project_dir" "$(id -un)" >"$render_dir/supermicro-observability.service"
systemd-analyze verify "$render_dir/supermicro-observability.service"
"$project_dir/scripts/render-management-command" "$project_dir" "$(id -un)" >"$render_dir/supermicro-observability"
bash -n "$render_dir/supermicro-observability"
if rg -n '@[A-Z][A-Z_]+@' "$render_dir/supermicro-observability"; then
    echo "management command contains unresolved placeholders" >&2
    exit 1
fi
grep -Fq 'app_dir=/opt/supermicro-observability' "$render_dir/supermicro-observability"
grep -Fq 'config_file=/etc/supermicro-observability/config.env' "$render_dir/supermicro-observability"
grep -Fq 'state_dir=/var/lib/supermicro-observability' "$render_dir/supermicro-observability"
grep -Fq "app_dir=/opt/supermicro-observability" "$project_dir/scripts/install-system.sh"
grep -Fq "config_dir=/etc/supermicro-observability" "$project_dir/scripts/install-system.sh"
grep -Fq "state_dir=/var/lib/supermicro-observability" "$project_dir/scripts/install-system.sh"
grep -Fq '.DEFAULT_GOAL := help' "$project_dir/Makefile"
grep -Fq "checkout-local monitoring is running" "$project_dir/scripts/install-system.sh"
grep -Fq "monitoring is already running outside systemd" "$render_dir/supermicro-observability"

expected_digests=6
actual_digests="$(grep -Ec '^    image: .+@sha256:[0-9a-f]{64}$' "$project_dir/compose.yaml")"
[[ "$actual_digests" -eq "$expected_digests" ]] || {
    echo "expected $expected_digests pinned upstream images, found $actual_digests" >&2
    exit 1
}

grep -Fq '${SMART_DEVICE_HOST:-/dev/null}:/dev/smart-target:r' "$project_dir/compose.yaml"
grep -Fq -- '--smartctl.device=/dev/smart-target;${SMART_DEVICE_TYPE:-auto}' "$project_dir/compose.yaml"
grep -Fq -- '--no-smartctl.scan' "$project_dir/compose.yaml"
grep -Fq 'profiles: ["nvidia"]' "$project_dir/compose.yaml"
grep -Fq 'profiles: ["smart"]' "$project_dir/compose.yaml"
grep -Fq 'GF_SECURITY_ADMIN_PASSWORD__FILE: /run/secrets/grafana-admin-password' "$project_dir/compose.yaml"
if grep -Fq 'GF_SECURITY_ADMIN_PASSWORD:' "$project_dir/compose.yaml"; then
    echo "Grafana password must be supplied through its credential file" >&2
    exit 1
fi
if grep -q '^GRAFANA_ADMIN_PASSWORD=' "$config_file"; then
    echo "Grafana password must not be stored in the host configuration file" >&2
    exit 1
fi
if grep -Eq '^[[:space:]]*-[[:space:]]*/dev/(nvme[0-9]|sd[a-z]|disk/by-id)' "$project_dir/compose.yaml"; then
    echo "compose.yaml must not contain a concrete host storage identity" >&2
    exit 1
fi
if grep -Eq 'nvme[0-9]+n[0-9]+' "$project_dir/grafana/dashboards/"*.json; then
    echo "dashboards must not contain a concrete NVMe kernel name" >&2
    exit 1
fi
if rg -n 'supermicro-fan-control|ipmitool' \
    "$project_dir/scripts/monitoring-mode" \
    "$project_dir/scripts/install-system.sh" \
    "$project_dir/scripts/rollback-system.sh" \
    "$project_dir/scripts/supermicro-observability.in" \
    "$project_dir/systemd/supermicro-observability.service.in"; then
    echo "core lifecycle must not manage or poll fan control" >&2
    exit 1
fi

[[ "$(stat -c '%a' "$config_file")" == "600" || "$(stat -c '%a' "$config_file")" == "640" ]]
[[ "$(stat -c '%a' "$project_dir/runtime/secrets/grafana-admin-password")" == "600" ]]
git -C "$project_dir" check-ignore -q .env
git -C "$project_dir" check-ignore -q runtime/secrets/grafana-admin-password
git -C "$project_dir" check-ignore -q runtime/prometheus/prometheus.yml

echo "Static validation passed."
