# Security policy

## Supported versions

The latest release and the default branch receive security fixes. Older
snapshots are supported only when explicitly documented.

## Reporting a vulnerability

Use the repository's private GitHub Security Advisory reporting channel when
available. Do not open a public issue containing credentials, identifying host
data, private metric output, or an exploit that could endanger cooling or
storage. Include the affected version, deployment assumptions, reproduction
steps, and the least harmful proof of concept possible.

The stack is not an Internet-facing service. Its intended boundary is
loopback-only listeners reached through an authenticated SSH tunnel. Treat any
non-loopback bind, automatic storage scan, new device pass-through, Docker
socket access, or fan-control change as security- and safety-sensitive.

Upstream image vulnerabilities should identify the pinned image name and digest
so that remediation remains reproducible.
