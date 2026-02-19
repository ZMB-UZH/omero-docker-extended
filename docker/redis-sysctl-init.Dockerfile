FROM alpine:3.23

COPY docker/redis-sysctl-init.sh /usr/local/bin/redis-sysctl-init
RUN chmod 0555 /usr/local/bin/redis-sysctl-init

ENTRYPOINT ["/usr/local/bin/redis-sysctl-init"]
