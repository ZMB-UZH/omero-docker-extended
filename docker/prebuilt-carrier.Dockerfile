FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

RUN addgroup -S carrier \
    && adduser -S -D -H -G carrier carrier \
    && mkdir -p /omero-prebuilt \
    && chown carrier:carrier /omero-prebuilt \
    && chmod 0555 /omero-prebuilt

COPY --chown=carrier:carrier --chmod=0444 prebuilt-manifest.json /omero-prebuilt/prebuilt-manifest.json
COPY --chown=carrier:carrier --chmod=0444 prebuilt-required-images.txt /omero-prebuilt/prebuilt-required-images.txt
COPY --chown=carrier:carrier --chmod=0444 runtime-images.tar.gz /omero-prebuilt/runtime-images.tar.gz

USER carrier

HEALTHCHECK --interval=1h --timeout=5s --start-period=5s --retries=1 \
    CMD test -r /omero-prebuilt/prebuilt-manifest.json \
    && test -r /omero-prebuilt/prebuilt-required-images.txt \
    && test -r /omero-prebuilt/runtime-images.tar.gz \
    || exit 1

CMD ["sh", "-c", "printf '%s\\n' 'OMERO Docker Extended prebuilt carrier image. Use installation/easy_installation_script.sh.'"]
