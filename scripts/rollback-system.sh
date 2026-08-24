#!/usr/bin/env bash
set -Eeuo pipefail

manager=/usr/local/sbin/supermicro-observability
[[ -x "$manager" ]] || {
    echo "management command is not installed: $manager" >&2
    exit 1
}
exec "$manager" uninstall
