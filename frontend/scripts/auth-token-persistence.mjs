// Exercise the real API module without mounting a settings component. The mocked
// transport resolves after the caller has left, so only API-owned storage runs.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

let respond;
const storage = new Map([['finance_access_token', 'old-token']]);
const paths = [];
const api = {
    interceptors: { request: { use() {} }, response: { use() {} } },
    post: (path) => { paths.push(path); return new Promise((resolve) => { respond = resolve; }); },
    patch: (path) => { paths.push(path); return new Promise((resolve) => { respond = resolve; }); },
};
const source = (await readFile(new URL('../src/api/index.ts', import.meta.url), 'utf8'))
    .replace('import.meta.env.VITE_API_URL', 'undefined');
const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
});
const exports = {};
vm.runInNewContext(outputText, {
    exports,
    require: (name) => {
        if (name === 'axios') return { create: () => api };
        if (name === '../studio/i18n') return { activeLanguage: () => 'en' };
        throw new Error(`Unexpected runtime dependency: ${name}`);
    },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
});
const replacing = exports.verifyMfaReplacement({ code: '123456' });
assert.equal(storage.get('finance_access_token'), 'old-token');
respond({ data: { access_token: 'replacement-token', recovery_codes: [] } });
await replacing;
assert.equal(storage.get('finance_access_token'), 'replacement-token');
const changing = exports.updateProfile({ password: 'new-password', current_password: 'old-password' });
respond({ data: { access_token: 'password-token', message: 'Updated' } });
await changing;
assert.equal(storage.get('finance_access_token'), 'password-token');
const renaming = exports.updateProfile({ name: 'Name' });
respond({ data: { message: 'Updated' } });
await renaming;
assert.equal(storage.get('finance_access_token'), 'password-token');
assert.deepEqual(paths, ['/auth/mfa/replace/verify', '/auth/me', '/auth/me']);
console.log('Settings API persists rotated tokens before returning, without mounted components');
