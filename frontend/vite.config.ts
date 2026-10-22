import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  server: {
    host: true,   // for Cloudflare Tunnel
    port: 15173,
  },
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/mark.svg', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/maskable-512.png'],
      manifest: {
        name: 'AssetManagement',
        short_name: 'AssetManagement',
        description: 'Personal asset management workspace',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        // The light workspace behind the app, as index.html's theme-color.
        background_color: '#f6f5f0',
        theme_color: '#f6f5f0',
        icons: [
          {
            src: '/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
          {
            src: '/icons/maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api\//, /^\/auth\//],
      },
    }),
  ],
})
