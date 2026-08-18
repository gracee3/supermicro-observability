#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
project_dir="$(cd -- "$script_dir/.." && pwd -P)"
duration="${1:-300}"
interval=5
if [[ ! "$duration" =~ ^[0-9]+$ ]] || (( duration < interval )); then
    echo "usage: observer-check.sh [duration-seconds>=5]" >&2
    exit 2
fi

mapfile -t containers < <(docker compose --project-directory "$project_dir" --file "$project_dir/compose.yaml" --profile nvidia --profile smart --profile containers ps -q)
(( ${#containers[@]} > 0 )) || {
    echo "no monitoring containers are running" >&2
    exit 1
}

samples=$((duration / interval))
cpu_sum=0
gpu_cpu_sum=0
memory_max=0
started_at="$SECONDS"

for ((sample = 1; sample <= samples; sample++)); do
    snapshot="$(docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' "${containers[@]}")"
    read -r sample_cpu sample_gpu_cpu sample_memory < <(
        awk -F '|' '
            function bytes(value, number, unit) {
                split(value, parts, " ")
                number=parts[1]+0
                unit=parts[1]
                sub(/^[0-9.]+/, "", unit)
                if (unit == "KiB") return number*1024
                if (unit == "MiB") return number*1024*1024
                if (unit == "GiB") return number*1024*1024*1024
                if (unit == "kB") return number*1000
                if (unit == "MB") return number*1000*1000
                if (unit == "GB") return number*1000*1000*1000
                return number
            }
            {
                cpu=$2
                sub(/%$/, "", cpu)
                split($3, memory, " / ")
                total_cpu += cpu
                total_memory += bytes(memory[1])
                if ($1 == "supermicro-fast-gpu-exporter") gpu_cpu += cpu
            }
            END { printf "%.6f %.6f %.0f\n", total_cpu, gpu_cpu, total_memory }
        ' <<<"$snapshot"
    )
    cpu_sum="$(awk -v a="$cpu_sum" -v b="$sample_cpu" 'BEGIN { printf "%.6f", a+b }')"
    gpu_cpu_sum="$(awk -v a="$gpu_cpu_sum" -v b="$sample_gpu_cpu" 'BEGIN { printf "%.6f", a+b }')"
    (( sample_memory > memory_max )) && memory_max="$sample_memory"
    if (( sample < samples )); then
        next_sample_at=$((started_at + sample * interval))
        sleep_for=$((next_sample_at - SECONDS))
        (( sleep_for > 0 )) && sleep "$sleep_for"
    fi
done

cpu_average="$(awk -v sum="$cpu_sum" -v count="$samples" 'BEGIN { printf "%.3f", sum/count }')"
gpu_cpu_average="$(awk -v sum="$gpu_cpu_sum" -v count="$samples" 'BEGIN { printf "%.3f", sum/count }')"
memory_mib="$(awk -v bytes="$memory_max" 'BEGIN { printf "%.1f", bytes/1024/1024 }')"

printf 'fast GPU exporter average CPU: %s%% of one logical CPU\n' "$gpu_cpu_average"
printf 'complete stack average CPU: %s%% of one logical CPU\n' "$cpu_average"
printf 'maximum aggregate container memory: %s MiB\n' "$memory_mib"

fail=0
awk -v value="$gpu_cpu_average" 'BEGIN { exit !(value < 2.0) }' || {
    echo "FAIL: fast GPU exporter CPU is not below 2%" >&2
    fail=1
}
awk -v value="$cpu_average" 'BEGIN { exit !(value < 10.0) }' || {
    echo "FAIL: complete stack CPU is not below 10%" >&2
    fail=1
}
(( memory_max < 1073741824 )) || {
    echo "FAIL: aggregate monitoring memory is not below 1 GiB" >&2
    fail=1
}

unhealthy="$(curl --fail --silent --get \
    --data-urlencode 'query=up == 0' \
    http://127.0.0.1:9090/api/v1/query)"
if [[ "$unhealthy" != *'"result":[]'* ]]; then
    echo "FAIL: Prometheus has down targets: $unhealthy" >&2
    fail=1
fi

exit "$fail"
