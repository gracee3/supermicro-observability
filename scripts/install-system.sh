#!/usr/bin/env bash
set -Eeuo pipefail

(( EUID == 0 )) || {
    echo "run this installer with sudo" >&2
    exit 1
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
service_user="${OBSERVABILITY_USER:-$(stat -c '%U' "$project_dir")}"
service_group="$(id -gn "$service_user")"

app_dir=/opt/supermicro-observability
config_dir=/etc/supermicro-observability
config_file="$config_dir/config.env"
password_file="$config_dir/grafana-admin-password"
state_dir=/var/lib/supermicro-observability
runtime_dir="$state_dir/runtime"
data_dir="$state_dir/data"
build_dir="$state_dir/build/gpu-exporter"
manager=/usr/local/sbin/supermicro-observability
unit=/etc/systemd/system/supermicro-observability.service
source_config="$project_dir/.env"
source_password="$project_dir/runtime/secrets/grafana-admin-password"

getent passwd "$service_user" >/dev/null || {
    echo "observability service user does not exist: $service_user" >&2
    exit 1
}

if systemctl is-active --quiet supermicro-observability.service; then
    echo "stop supermicro-observability before reinstalling it" >&2
    exit 1
fi

local_running=""
if ! local_running="$(
    runuser -u "$service_user" -- docker ps \
        --filter label=com.docker.compose.project=supermicro-observability \
        --quiet
)"; then
    echo "could not determine whether checkout-local monitoring is running" >&2
    exit 1
fi
if [[ -n "$local_running" ]]; then
    echo "checkout-local monitoring is running; run 'make stop' before system installation" >&2
    exit 1
fi

if [[ ! -f "$config_file" ]]; then
    if [[ -f "$source_config" ]]; then
        runuser -u "$service_user" -- "$project_dir/scripts/doctor" --quiet
    else
        echo "host profile is missing; run make install-system without sudo so it can configure the host" >&2
        exit 1
    fi
fi

install -d -o root -g root -m 0755 /opt
stage_dir="$(mktemp -d /opt/.supermicro-observability.install.XXXXXX)"
backup_dir=""
render_dir=""
install_succeeded=0
cleanup() {
    local status=$?
    [[ -z "${stage_dir:-}" || ! -d "$stage_dir" ]] || rm -rf -- "$stage_dir"
    [[ -z "${render_dir:-}" || ! -d "$render_dir" ]] || rm -rf -- "$render_dir"
    if [[ -n "${backup_dir:-}" && -d "$backup_dir" ]]; then
        if (( install_succeeded )); then
            rm -rf -- "$backup_dir"
        else
            rm -rf -- "$app_dir"
            mv -- "$backup_dir" "$app_dir"
        fi
    fi
    return "$status"
}
trap cleanup EXIT

for directory in docs gpu-exporter grafana prometheus scripts systemd; do
    cp -a -- "$project_dir/$directory" "$stage_dir/"
done
for file in AGENTS.md CHANGELOG.md CITATION.cff LICENSE NOTICE README.md SECURITY.md THIRD_PARTY.md compose.yaml; do
    cp -a -- "$project_dir/$file" "$stage_dir/"
done
rm -rf -- "$stage_dir/gpu-exporter/target" "$stage_dir/scripts/__pycache__"
chown -R root:root "$stage_dir"

if [[ -d "$app_dir" ]]; then
    backup_dir="$(mktemp -d /opt/.supermicro-observability.previous.XXXXXX)"
    rmdir -- "$backup_dir"
    mv -- "$app_dir" "$backup_dir"
fi
mv -- "$stage_dir" "$app_dir"
stage_dir=""

install -d -o root -g "$service_group" -m 0750 "$config_dir" "$state_dir"
install -d -o "$service_user" -g "$service_group" -m 0750 \
    "$runtime_dir" \
    "$runtime_dir/prometheus" \
    "$runtime_dir/prometheus/file_sd" \
    "$runtime_dir/textfile_collector" \
    "$data_dir" \
    "$data_dir/grafana" \
    "$data_dir/prometheus" \
    "$state_dir/build" \
    "$build_dir"
install -o root -g root -m 0644 "$app_dir/gpu-exporter/Dockerfile" "$build_dir/Dockerfile"

for service in grafana prometheus; do
    if [[ -d "$project_dir/data/$service" ]] && \
        ! find "$data_dir/$service" -mindepth 1 -print -quit | grep -q .; then
        cp -a -- "$project_dir/data/$service/." "$data_dir/$service/"
        rm -f -- "$data_dir/$service/.gitkeep"
    fi
done

if [[ ! -f "$config_file" ]]; then
    install -o root -g "$service_group" -m 0640 "$source_config" "$config_file"
fi
if [[ ! -f "$password_file" ]]; then
    if [[ -f "$source_password" ]]; then
        install -o root -g "$service_group" -m 0640 "$source_password" "$password_file"
    elif grep -q '^GRAFANA_ADMIN_PASSWORD=' "$config_file"; then
        : # host_config migrates the legacy inline value below
    else
        echo "Grafana password is missing; rerun scripts/configure-host in the source checkout" >&2
        exit 1
    fi
fi

configured_uid="$(sed -n 's/^OBSERVABILITY_UID=//p' "$config_file")"
configured_gid="$(sed -n 's/^OBSERVABILITY_GID=//p' "$config_file")"
if [[ "$configured_uid" != "$(id -u "$service_user")" || \
      "$configured_gid" != "$(id -g "$service_user")" ]]; then
    echo "configured observability UID/GID do not match service user $service_user" >&2
    exit 1
fi

if grep -qx 'FAN_METRICS_MODE=disabled' "$config_file"; then
    sed -i "s|^TEXTFILE_COLLECTOR_DIR=.*$|TEXTFILE_COLLECTOR_DIR=$runtime_dir/textfile_collector|" "$config_file"
fi

export OBSERVABILITY_CONFIG_FILE="$config_file"
export GRAFANA_PASSWORD_FILE="$password_file"
export OBSERVABILITY_RUNTIME_DIR="$runtime_dir"
export OBSERVABILITY_DATA_DIR="$data_dir"
export OBSERVABILITY_BUILD_DIR="$build_dir"
export GPU_EXPORTER_BUILD_CONTEXT="$build_dir"

"$app_dir/scripts/configure-host" --non-interactive --apply --quiet
chown root:"$service_group" "$config_file" "$password_file"
chmod 0640 "$config_file" "$password_file"
chown -R "$service_user":"$service_group" "$runtime_dir" "$data_dir"

render_dir="$(mktemp -d)"
"$app_dir/scripts/render-systemd-unit" "$app_dir" "$service_user" >"$render_dir/supermicro-observability.service"
"$app_dir/scripts/render-management-command" "$app_dir" "$service_user" >"$render_dir/supermicro-observability"

install -o root -g root -m 0644 "$render_dir/supermicro-observability.service" "$unit"
install -o root -g root -m 0755 "$render_dir/supermicro-observability" "$manager"
systemd-analyze verify "$unit"
systemctl daemon-reload
systemctl disable supermicro-observability.service >/dev/null 2>&1 || true

runuser -u "$service_user" -- env \
    OBSERVABILITY_CONFIG_FILE="$config_file" \
    GRAFANA_PASSWORD_FILE="$password_file" \
    OBSERVABILITY_RUNTIME_DIR="$runtime_dir" \
    OBSERVABILITY_DATA_DIR="$data_dir" \
    OBSERVABILITY_BUILD_DIR="$build_dir" \
    GPU_EXPORTER_BUILD_CONTEXT="$build_dir" \
    "$app_dir/scripts/doctor" --quiet

echo "Monitoring installed under $app_dir and disabled at boot; it was not started."
echo "Configuration: $config_file"
echo "Persistent state: $state_dir"
echo "Grafana admin password: $(cat "$password_file")"
echo "Password file: $password_file"
echo "Start on demand with: sudo $manager start"
echo "The source checkout may now be deleted."
echo "Fan-controller files and services were not modified."
install_succeeded=1
