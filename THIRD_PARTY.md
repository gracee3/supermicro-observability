# Third-party components

This repository contains configuration that refers to, but does not redistribute,
the following container images. Each component remains governed by its upstream
license, notices, and trademarks.

| Component | Pinned version | Upstream source |
|---|---|---|
| Prometheus | `v3.13.2-distroless` | <https://github.com/prometheus/prometheus> |
| Grafana | `13.1.3` | <https://github.com/grafana/grafana> |
| node_exporter | `v1.12.1` | <https://github.com/prometheus/node_exporter> |
| nvidia_gpu_exporter | `1.14.0-nvml` | <https://github.com/utkuozdemir/nvidia_gpu_exporter> |
| smartctl_exporter | `v0.14.0` | <https://github.com/prometheus-community/smartctl_exporter> |
| cAdvisor | `v0.60.5` | <https://github.com/google/cadvisor> |
| Debian base image | `bookworm-slim` digest-pinned | <https://hub.docker.com/_/debian> |

The NVIDIA driver, `nvidia-smi`, NVIDIA Container Toolkit, Docker, Rust, Linux,
systemd, `ipmitool`, and the separately maintained fan controller are runtime or
build dependencies and are not copied into this repository.

Resolved image digests are recorded in `compose.yaml` and the GPU exporter's
`Dockerfile`. Before redistribution, audit the exact artifacts and retain all
notices required by their upstream licenses.
