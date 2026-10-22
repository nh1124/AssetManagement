import { copyFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
    appType: 'mpa',
    cacheDir: '.cache/vite-admin',
    plugins: [react(), tailwindcss(), {
        // AdminSPA serves index.html for / and client-side routes.
        name: 'admin-spa-entry',
        configureServer(server) {
            // Vite otherwise serves the user app's index.html at / and SPA routes.
            server.middlewares.use((request, _response, next) => {
                const pathname = (request.url ?? '/').split('?')[0];
                if ((request.method === 'GET' || request.method === 'HEAD')
                    && !pathname.startsWith('/admin/api')
                    && (pathname === '/' || pathname === '/index.html' || request.headers.accept?.includes('text/html'))) {
                    request.url = '/admin.html';
                }
                next();
            });
        },
        async writeBundle(options) {
            const out = resolve(options.dir ?? 'dist-admin');
            await copyFile(resolve(out, 'admin.html'), resolve(out, 'index.html'));
        },
    }],
    server: {
        host: '127.0.0.1',
        port: 15380,
        strictPort: true,
        proxy: { '/admin/api': { target: 'http://127.0.0.1:18300' } },
    },
    build: { outDir: 'dist-admin', rollupOptions: { input: 'admin.html' } },
});
