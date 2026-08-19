import { copyFile, mkdir } from 'node:fs/promises';

const releaseAssets = ['index.html', 'styles.css'];

export async function copyReleaseAssets() {
  await mkdir('dist', { recursive: true });
  await Promise.all(
    releaseAssets.map((asset) => copyFile(asset, `dist/${asset}`)),
  );
}
