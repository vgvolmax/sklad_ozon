import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

test('Static `file://` shell', () => {
  assert.equal(existsSync('app/index.html'), true);

  const html = readFileSync('app/index.html', 'utf8');
  assert.match(html, /href="\.\/assets\/css\/app\.css"/);
  assert.match(html, /src="\.\/assets\/js\/app\.js"/);
  assert.doesNotMatch(html, /type="module"|(?:https?:\/\/)|localhost|["']\/assets\//i);
  assert.doesNotMatch(html, /\b(?:server|api\/|service\s*worker|runtime bootstrap)\b/i);
  assert.equal(existsSync('start.bat'), false);
});
