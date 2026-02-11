# Pull image (needs to match the tag in docker-compose.yml)
# ---------------------------------------------------------
FROM alpine:3.21

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init
RUN chmod 0555 /usr/local/bin/redis-sysctl-init

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
