FROM alpine:3.24.3@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

ARG PYTHON_APK_VERSION=3.14.8-r0
ARG PIP_APK_VERSION=26.1.2-r0
ARG CA_CERTIFICATES_APK_VERSION=20261020-r0
ARG ZLIB_APK_VERSION=1.3.2-r1
RUN apk add --no-cache "python3=${PYTHON_APK_VERSION}" \
    "py3-pip=${PIP_APK_VERSION}" "ca-certificates=${CA_CERTIFICATES_APK_VERSION}" \
    "zlib=${ZLIB_APK_VERSION}"
COPY --chmod=0444 monitoring/tls/requirements.txt /build/requirements.txt
RUN python3 -m venv --without-pip /opt/tls && \
    python3 -m pip --python /opt/tls/bin/python install --no-cache-dir \
      --require-hashes -r /build/requirements.txt && \
    apk del py3-pip && rm -rf /build

WORKDIR /app
COPY --chmod=0444 monitoring/tls/*.py /app/monitoring/tls/
COPY --chmod=0444 monitoring/tls/identities.json /etc/omero-tls/identities.json
# COPY file modes also apply to newly created parent directories.
RUN chmod 0555 /app/monitoring /app/monitoring/tls /etc/omero-tls && \
    mkdir -p /pki/private /pki/trust /pki/servers/database \
      /pki/servers/database_plugin /pki/servers/grafana \
      /pki/servers/loki /pki/servers/prometheus && \
    chmod 0700 /pki/private && \
    chmod 0755 /pki /pki/trust /pki/servers /pki/servers/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Compose grants root only to the isolated, networkless volume owner.
USER 65532:65532
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["/opt/tls/bin/python", "-m", "monitoring.tls.manager", "check", "--root", "/pki", "--identities", "/etc/omero-tls/identities.json"]
ENTRYPOINT ["/opt/tls/bin/python", "-m", "monitoring.tls.manager"]
CMD ["serve", "--root", "/pki", "--identities", "/etc/omero-tls/identities.json"]
