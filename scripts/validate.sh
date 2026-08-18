#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
fan_dir="${FAN_CONTROL_DIR:-$project_dir/../supermicro-fan-control}"
compose=(docker compose --project-directory "$project_dir" --file "$project_dir/compose.yaml")

"${compose[@]}" config --quiet

docker run --rm \
    --entrypoint /bin/promtool \
    -v "$project_dir/prometheus:/etc/prometheus:ro" \
    prom/prometheus:v3.13.2-distroless@sha256:64f71bb84e03c855948418b0fc5dea53e9543d8e3fc9931598f583805507f05e \
    check config /etc/prometheus/prometheus.yml

for dashboard in "$project_dir"/grafana/dashboards/*.json; do
    python3 -m json.tool "$dashboard" >/dev/null
done
python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' \
    "$project_dir/scripts/generate-dashboards.py"

cargo fmt --manifest-path "$project_dir/gpu-exporter/Cargo.toml" -- --check
cargo test --quiet --manifest-path "$project_dir/gpu-exporter/Cargo.toml"
cargo clippy --quiet --manifest-path "$project_dir/gpu-exporter/Cargo.toml" --all-targets -- -D warnings

bash -n "$project_dir/scripts/monitoring-mode"
bash -n "$project_dir/scripts/container-metrics"
bash -n "$project_dir/scripts/observer-check.sh"
bash -n "$project_dir/scripts/install-system.sh"
bash -n "$project_dir/scripts/rollback-system.sh"
bash -n "$project_dir/scripts/render-systemd-unit"
if [[ -f "$fan_dir/supermicro-fan-control" && -f "$fan_dir/supermicro-fan-control.service" ]]; then
    bash -n "$fan_dir/supermicro-fan-control"
    systemd-analyze verify "$fan_dir/supermicro-fan-control.service"
else
    printf 'NOTICE: external fan-controller checkout not found at %s; integration validation skipped.\n' "$fan_dir"
fi

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

grep -q '/dev/nvme1n1:/dev/nvme1n1:r' "$project_dir/compose.yaml"
if grep -Eq '^ +-[[:space:]]*/dev/nvme0n1:' "$project_dir/compose.yaml"; then
    echo "protected /dev/nvme0n1 must never be passed to a container" >&2
    exit 1
fi

echo "Static validation passed."
