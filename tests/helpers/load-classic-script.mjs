import { readFileSync } from 'node:fs';
import vm from 'node:vm';

export function loadClassicScripts(paths, globals = {}) {
  if (!Array.isArray(paths) || paths.length === 0) {
    throw new TypeError('paths must be a non-empty array');
  }

  const context = { console, ...globals };
  context.globalThis = context;
  vm.createContext(context);

  for (const path of paths) {
    const source = readFileSync(path, 'utf8');
    vm.runInContext(source, context, { filename: path });
  }

  if (!context.SkladOzon) {
    throw new Error('SkladOzon namespace was not created');
  }

  return context.SkladOzon;
}
