FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

RUN addgroup -S carrier \
    && adduser -S -D -H -G carrier carrier

COPY prebuilt-manifest.json /omero-prebuilt/prebuilt-manifest.json
COPY prebuilt-required-images.txt /omero-prebuilt/prebuilt-required-images.txt
COPY runtime-images.tar.gz /omero-prebuilt/runtime-images.tar.gz

RUN chown -R carrier:carrier /omero-prebuilt \
    && chmod 0444 /omero-prebuilt/prebuilt-manifest.json \
    && chmod 0444 /omero-prebuilt/prebuilt-required-images.txt \
    && chmod 0444 /omero-prebuilt/runtime-images.tar.gz

USER carrier

CMD ["sh", "-c", "printf '%s\\n' 'OMERO Docker Extended prebuilt carrier image. Use installation/easy_installation_script.sh.'"]
