# Vizarr Vendored Build

- Upstream repository: <https://github.com/hms-dbmi/vizarr>
- Upstream branch: `main`
- Upstream commit: `be7ccc260e848a2829873c8746f32b4f43599435`
- Local payload: production build output under `dist/`
- License: MIT, preserved in `dist/LICENSE`

Build command used for this snapshot:

```bash
corepack pnpm@9.5.0 install --frozen-lockfile
VIZARR_PREFIX=./ corepack pnpm@9.5.0 build
```

Source maps are not vendored. The runtime package copies this exact `dist/`
tree into `omero_web_zarr/static/omero_web_zarr/vendor/vizarr/<commit>/`
during the OMERO.web image build.
