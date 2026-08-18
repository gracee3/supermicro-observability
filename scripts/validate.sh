#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
compose=(docker compose --project-directory "$project_dir" --file "$project_dir/compose.yaml")

"$project_dir/scripts/doctor" --quiet
"${compose[@]}" --profile nvidia --profile smart --profile containers config --quiet

docker run --rm \
    --entrypoint /bin/promtool \
    -v "$project_dir/runtime/prometheus:/etc/prometheus:ro" \
    prom/prometheus:v3.13.2-distroless@sha256:64f71bb84e03c855948418b0fc5dea53e9543d8e3fc9931598f583805507f05e \
    check config /etc/prometheus/prometheus.yml

for target in "$project_dir"/runtime/prometheus/file_sd/*.json; do
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
    configure-host \
    doctor \
    install-system.sh \
    rollback-system.sh \
    install-fan-integration.sh \
    rollback-fan-integration.sh \
    render-systemd-unit; do
    bash -n "$project_dir/scripts/$script"
done

render_dir="$(mktemp -d)"
trap 'rm -rf -- "$render_dir"' EXIT
"$project_dir/scripts/render-systemd-unit" "$project_dir" "$(id -un)" >"$render_dir/supermicro-observability.service"
systemd-analyze verify "$render_dir/supermicro-observability.service"

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
    "$project_dir/systemd/supermicro-observability.service.in"; then
    echo "core lifecycle must not manage or poll fan control" >&2
    exit 1
fi

[[ "$(stat -c '%a' "$project_dir/.env")" == "600" ]]
git -C "$project_dir" check-ignore -q .env
git -C "$project_dir" check-ignore -q runtime/prometheus/prometheus.yml

echo "Static validation passed."
