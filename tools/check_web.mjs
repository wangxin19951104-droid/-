// Parse scripts without running page code or submitting any work.
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let checked = 0;
for (const name of ['journey.js', 'intelligence.js']) {
  new vm.Script(await fs.readFile(path.join(root, 'web', name), 'utf8'), { filename: name });
  checked++;
}
const html = await fs.readFile(path.join(root, 'web', 'index.html'), 'utf8');
for (const [index, match] of [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)].entries()) {
  if (/\bsrc\s*=/i.test(match[1]) || /(?:application\/json|ld\+json)/i.test(match[1])) continue;
  new vm.Script(match[2], { filename: 'index.html:inline-' + index });
  checked++;
}
console.log('JavaScript syntax OK: ' + checked + ' scripts.');
