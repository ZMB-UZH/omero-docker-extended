FROM docker:27.4.0-cli

USER root

RUN set -euo pipefail; \
    apk add --no-cache util-linux

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
