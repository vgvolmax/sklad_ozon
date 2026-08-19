import { rm } from 'node:fs/promises';
import { build } from 'esbuild';
import { copyReleaseAssets } from './copy-release-assets.mjs';

await rm('dist', { force: true, recursive: true });

await build({
  bundle: true,
  entryPoints: ['src/app/bootstrap.ts'],
  format: 'iife',
  outfile: 'dist/app.js',
  platform: 'browser',
  target: ['es2020'],
});

await copyReleaseAssets();
