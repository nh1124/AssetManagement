import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, relative } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
async function files(dir) {
    const entries = await readdir(dir, { withFileTypes: true });
    return (await Promise.all(entries.map(e => e.isDirectory() ? files(resolve(dir, e.name)) : [resolve(dir, e.name)]))).flat();
}
const checks = [
    ['dist', ['/admin/api', 'src/admin', 'src\\admin']],
    ['dist-admin', ['/plan/', '/transactions', '/capsules/', '/reports/monthly', '/budget-plans/']],
];
let failed = false;
for (const [dir, forbidden] of checks) {
    const entries = await files(resolve(root, dir)); // Missing builds fail too.
    if (!entries.some(file => file.endsWith('.js'))) throw new Error(`${dir}: no JavaScript bundle`);
    for (const file of entries) {
        if (!/\.(js|css|html|json|map)$/.test(file)) continue;
        const content = await readFile(file, 'utf8');
        for (const marker of forbidden) {
            if (content.includes(marker)) {
                console.error(`${relative(root, file)} contains forbidden marker: ${marker}`);
                failed = true;
            }
        }
    }
}
if (failed) process.exitCode = 1;
else console.log('PASS: user and administrator bundles are separate.');
