import { dirname, resolve } from 'node:path';
import { createRequire } from 'node:module';

import vitePreviewConfig from './vite_django_preview.config.mjs';

const requireFromToolDir = createRequire(resolve(process.cwd(), 'package.json'));
const { defineConfig, mergeConfig } = requireFromToolDir('vitest/config');
const vitestPackageRoot = dirname(requireFromToolDir.resolve('vitest/package.json'));
const vitestEntry = resolve(vitestPackageRoot, 'dist/index.js');
const vitestConfigEntry = resolve(vitestPackageRoot, 'dist/config.js');
const vitestInternalBrowserEntry = resolve(vitestPackageRoot, 'dist/browser.js');
const vitestBrowserContextEntry = requireFromToolDir.resolve('@vitest/browser/context');

const browserEnabled = process.env.VITEST_BROWSER === '1';
const browserHeadless = process.env.VITEST_BROWSER_HEADLESS !== '0';
const browserName = process.env.VITEST_BROWSER_NAME || 'chromium';

const browserConfig = browserEnabled
  ? (() => {
      const { playwright } = requireFromToolDir('@vitest/browser-playwright');
      return {
        browser: {
          enabled: true,
          headless: browserHeadless,
          provider: playwright(),
          instances: [{ browser: browserName }],
        },
      };
    })()
  : {};

export default mergeConfig(
  vitePreviewConfig,
  defineConfig({
    resolve: {
      alias: [
        { find: /^vitest\/internal\/browser$/, replacement: vitestInternalBrowserEntry },
        { find: /^vitest\/config$/, replacement: vitestConfigEntry },
        { find: /^@vitest\/browser\/context$/, replacement: vitestBrowserContextEntry },
        { find: /^vitest$/, replacement: vitestEntry },
      ],
    },
    test: {
      globals: true,
      include: [process.env.VITEST_INCLUDE || '**/*.vitest.{js,mjs,cjs,ts,mts,cts}'],
      passWithNoTests: false,
      css: true,
      ...(browserEnabled ? {} : { environment: 'jsdom' }),
      ...browserConfig,
    },
  }),
);
