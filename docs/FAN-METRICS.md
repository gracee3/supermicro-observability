# Optional fan metrics contract

The observability core never polls IPMI and never requires a particular fan
controller. It reads Prometheus textfiles through node_exporter. A controller or
adapter may implement the metrics below from a sample it already collected.

Write the completed file atomically, normally by creating a temporary file in
the same directory, setting appropriate permissions, and renaming it to
`supermicro_fan.prom`. Do not expose raw error text, command lines, credentials,
or unbounded labels.

| Metric | Type | Required labels | Meaning |
|---|---|---|---|
| `supermicro_fan_speed_rpm` | gauge | `fan` | Cached tachometer reading |
| `supermicro_fan_zone_duty_percent` | gauge | `zone` | Controller duty target |
| `supermicro_fan_temperature_celsius` | gauge | `sensor_group` | Aggregated control input |
| `supermicro_fan_controller_active` | gauge | none | `1` while the controller policy is active |
| `supermicro_fan_controller_failsafe` | gauge | none | `1` while the controller is in fail-safe |
| `supermicro_fan_sensor_read_healthy` | gauge | none | Health of the cached controller sample |
| `supermicro_fan_sample_timestamp_seconds` | gauge | none | Unix timestamp of that sample |

The `fan`, `zone`, and `sensor_group` label sets must be finite and documented by
the integration. A missing file or metric means unavailable data; monitoring
must not infer that cooling is safe. Alerting or dashboards should treat an old
timestamp as stale independently of controller-active state.

Controller implementation, BMC commands, fan-header mapping, calibrated curves,
stop hooks, and fail-safe behavior belong to the controller project or a reviewed
platform adapter. They are outside the generic monitoring contract.
