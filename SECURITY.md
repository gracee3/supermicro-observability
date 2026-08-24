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

The stack is not an Internet-facing service. Its default boundary is
loopback-only listeners reached through an authenticated SSH tunnel. Grafana
alone may bind to one exact private host address for a trusted direct link;
every metrics endpoint remains loopback-only. Treat broader exposure, automatic
storage scans, new device pass-through, Docker socket access, or fan-control
changes as security- and safety-sensitive.

Checkout-local operation keeps private configuration, the Grafana credential,
and mutable data in explicitly ignored files. The optional system installation
keeps application files under `/opt`, root-managed configuration and the
Grafana credential under `/etc`, and mutable monitoring state under `/var/lib`.
In both modes, the password is mounted into Grafana as a file rather than
exported in the Compose or systemd environment.

Upstream image vulnerabilities should identify the pinned image name and digest
so that remediation remains reproducible.
