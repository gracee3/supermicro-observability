FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241

COPY target/x86_64-unknown-linux-musl/release/supermicro-gpu-exporter /usr/local/bin/supermicro-gpu-exporter

USER 1000:1000
EXPOSE 9836
ENTRYPOINT ["/usr/local/bin/supermicro-gpu-exporter"]
