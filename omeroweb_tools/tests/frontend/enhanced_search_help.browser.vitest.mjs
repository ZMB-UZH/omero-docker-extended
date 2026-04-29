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
  document.title = parsed.title;

  const stylesheetHrefs = Array.from(parsed.querySelectorAll('link[rel="stylesheet"]'))
    .map((node) => node.getAttribute('href'))
    .filter(Boolean);

  for (const href of stylesheetHrefs) {
    const style = document.createElement('style');
    style.textContent = await fetchText(href);
    document.head.appendChild(style);
  }

  for (const sourceScript of parsed.querySelectorAll('script:not([src])')) {
    const script = document.createElement('script');
    script.textContent = sourceScript.textContent;
    document.body.appendChild(script);
  }

  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
};

describe('Enhanced Search HTML help page', () => {
  it('renders compact help with exact interface screenshots', async () => {
    await installHelpPage();

    const page = document.querySelector('.tools-help-page');
    const sectionToggle = document.querySelector('[data-tools-help-toggle]');
    const screenshots = Array.from(document.querySelectorAll('.tools-help-screenshot img'));

    expect(page).toBeTruthy();
    expect(document.title).toBe('Tools help');
    expect(document.querySelector('.admin-tools-title').textContent).toBe('Tools help');
    expect(sectionToggle.getAttribute('aria-expanded')).toBe('true');
    expect(sectionToggle.textContent).toContain('Enhanced search');
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

    expect(document.querySelectorAll('.tools-help-page button')).toHaveLength(1);
    const closeLink = document.querySelector('#tools-help-close-window');
    expect(closeLink.tagName).toBe('A');
    expect(closeLink.classList.contains('admin-tools-back-link')).toBe(true);
    expect(closeLink.textContent).toContain('Back to Enhanced search');
    expect(document.body.textContent).toContain('Troubleshooting');
    expect(document.body.textContent).toContain('Saved searches belong to your user account.');
    expect(document.body.textContent).not.toContain('Open Enhanced search');
    expect(document.body.textContent.toLowerCase()).not.toContain('password');
    expect(document.body.textContent).not.toContain('ghp_');
  });

  it('closes the help window and collapses the tool section without persistence', async () => {
    await installHelpPage();

    let closeCount = 0;
    const originalClose = window.close;
    window.close = () => {
      closeCount += 1;
    };

    document.querySelector('#tools-help-close-window').click();
    expect(closeCount).toBe(1);
    window.close = originalClose;

    const section = document.querySelector('[data-tools-help-section]');
    const toggle = document.querySelector('[data-tools-help-toggle]');
    const body = document.querySelector('[data-tools-help-body]');

    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.getAttribute('aria-hidden')).not.toBe('true');

    toggle.click();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(body.getAttribute('aria-hidden')).toBe('true');
    expect(section.classList.contains('tools-help-tool-section--collapsed')).toBe(true);

    await installHelpPage();
    expect(document.querySelector('[data-tools-help-toggle]').getAttribute('aria-expanded'))
      .toBe('true');
    expect(document.body.innerHTML).not.toContain('localStorage');
    expect(document.body.innerHTML).not.toContain('sessionStorage');
  });
});
