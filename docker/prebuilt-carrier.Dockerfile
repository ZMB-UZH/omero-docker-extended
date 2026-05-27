FROM scratch

COPY --chmod=0444 \
    prebuilt-manifest.json \
    prebuilt-required-images.txt \
    runtime-images.tar.gz \
    /omero-prebuilt/

# Scratch has no passwd database; numeric non-root metadata avoids an OS layer.
USER 65532:65532

HEALTHCHECK NONE

CMD ["/omero-prebuilt/carrier-data-only"]
