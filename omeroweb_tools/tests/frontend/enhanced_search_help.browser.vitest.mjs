import { describe, expect, it } from 'vitest';

const fetchText = async (url) => {
  const response = await fetch(url);
  expect(response.ok).toBe(true);
  return response.text();
};

const installHelpPage = async () => {
  const html = await fetchText('/help.html');
  const parsed = new DOMParser().parseFromString(html, 'text/html');

  document.head.innerHTML = '';
  document.body.innerHTML = parsed.body.innerHTML;

  const stylesheetHrefs = Array.from(parsed.querySelectorAll('link[rel="stylesheet"]'))
    .map((node) => node.getAttribute('href'))
    .filter(Boolean);

  for (const href of stylesheetHrefs) {
    const style = document.createElement('style');
    style.textContent = await fetchText(href);
    document.head.appendChild(style);
  }

  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
};

describe('Enhanced Search HTML help page', () => {
  it('renders compact help with exact interface screenshots', async () => {
    await installHelpPage();

    const page = document.querySelector('.tools-help-page');
    const screenshots = Array.from(document.querySelectorAll('.tools-help-screenshot img'));

    expect(page).toBeTruthy();
    expect(screenshots).toHaveLength(4);
    expect(getComputedStyle(page).minWidth).toBe('0px');
    expect(getComputedStyle(document.querySelector('.tools-help-panel')).borderLeftWidth)
      .toBe('4px');
    expect(getComputedStyle(document.querySelector('.tools-help-panel')).display).toBe('grid');
    expect(getComputedStyle(document.querySelector('.tools-help-panel--troubleshooting')).borderLeftColor)
      .toBe('rgb(217, 119, 6)');

    const screenshotPanels = Array.from(document.querySelectorAll('.tools-help-panel'))
      .filter((panel) => panel.querySelector('.tools-help-screenshot'));
    for (const panel of screenshotPanels) {
      const copyBox = panel.querySelector('.tools-help-copy').getBoundingClientRect();
      const screenshotBox = panel.querySelector('.tools-help-screenshot').getBoundingClientRect();

      expect(screenshotBox.top).toBeGreaterThan(copyBox.bottom);
      expect(Math.round(screenshotBox.left)).toBe(Math.round(copyBox.left));
    }

    await Promise.all(screenshots.map((image) => (
      image.complete && image.naturalWidth > 0
        ? Promise.resolve()
        : new Promise((resolve, reject) => {
          image.addEventListener('load', resolve, { once: true });
          image.addEventListener('error', reject, { once: true });
        })
    )));
    for (const image of screenshots) {
      expect(image.naturalWidth).toBeGreaterThanOrEqual(3000);
    }
    expect(document.querySelector('img[src$="enhanced-search-results.png"]').naturalHeight)
      .toBeGreaterThanOrEqual(1000);
  });

  it('keeps the help copy concise and user-facing', async () => {
    await installHelpPage();

    expect(document.querySelectorAll('.tools-help-page button')).toHaveLength(0);
    expect(document.body.textContent).toContain('Troubleshooting');
    expect(document.body.textContent).toContain('Saved searches belong to your user account.');
    expect(document.body.textContent).not.toContain('Open Enhanced search');
    expect(document.body.textContent.toLowerCase()).not.toContain('password');
    expect(document.body.textContent).not.toContain('ghp_');
  });
});
