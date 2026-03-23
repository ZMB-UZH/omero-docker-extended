// Here we configure a URL provider. This function will be passed the selected
// objects and the base URL that was specified in the "Open with" configuration above.
OME.setOpenWithUrlProvider("web_zarr_vizarr", function (selected, url) {
    const sourceUrl = new URL(`${url}v0.4/preview/image/${selected[0].id}.zarr`, window.location.origin);
    return `${url}vizarr/?source=${encodeURIComponent(sourceUrl.toString())}`;
});
