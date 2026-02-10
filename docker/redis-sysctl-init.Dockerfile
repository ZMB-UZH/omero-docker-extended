FROM docker:29.2.1-cli

USER root

RUN set -euo pipefail; \
    apk add --no-cache util-linux

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
