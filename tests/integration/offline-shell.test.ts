import { existsSync, readFileSync } from 'node:fs';
import { expect, it } from 'vitest';

it('builds a classic-script offline shell', () => {
  expect(existsSync('dist/index.html')).toBe(true);
  expect(existsSync('dist/app.js')).toBe(true);
  expect(existsSync('dist/styles.css')).toBe(true);

  const html = readFileSync('dist/index.html', 'utf8');
  expect(html).toContain('<script src="./app.js"></script>');
  expect(html).not.toContain('type="module"');
  expect(html).not.toMatch(/https?:\/\//);
});
