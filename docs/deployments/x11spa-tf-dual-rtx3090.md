# X11SPA-TF dual-RTX-3090 deployment case study

This document records one redacted deployment checked on 2026-08-17. It is an
example of a private host profile, not a portable hardware preset.

## Baseline

- Supermicro X11SPA-TF motherboard
- Intel Xeon Silver 4215R, 8 cores / 16 threads
- 96 GB nominal RAM
- two NVIDIA GeForce RTX 3090 GPUs with 24 GB each
- NVIDIA driver 610.43.02
- Docker Engine 29.7.2
- encrypted root under `/dev/mapper`
- one explicitly selected system SMART disk
- one distinct secondary disk required to remain read-only and unmounted
- cached metrics from a separately calibrated native fan controller

Actual disk by-id values, GPU UUIDs, network addresses, usernames, and fan-header
mapping are deliberately omitted. The private `.env` selects stable disks and
the `supermicro-x11spa-tf` DMI profile.

## Observed monitoring budget

A single five-minute normal-mode run observed:

- fast GPU exporter: 1.885% of one logical CPU on average;
- complete stack: 8.498% of one logical CPU on average;
- peak aggregate container memory: 285.8 MiB;
- node fast-scrape p95: 21.4 ms;
- GPU scrape p95: 1.78 ms; and
- approximately 6.9 KiB/s Prometheus growth during a separate 30-second sample.

These descriptive values have no confidence interval and should not be used as
a comparative benchmark. Ambient conditions, cache state, workloads, versions,
and Docker's own sampling affect them. See [Methodology](../METHODOLOGY.md).

## Cooling boundary

The controller's BMC protocol is associated with the platform, but its physical
fan mapping, RPM floors, curves, chassis airflow, cooler, and stop behavior were
calibrated for this machine. None of those values is supplied as a reusable
profile by this repository.
