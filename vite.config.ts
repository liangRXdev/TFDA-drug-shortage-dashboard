import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: '西藥供應資訊儀表板',
        short_name: 'Drug Short',
        description: '整合食藥署西藥供應短缺資訊，每週自動更新',
        theme_color: '#0891b2',
        background_color: '#f0f4f8',
        display: 'standalone',
        lang: 'zh-TW',
        start_url: '/TFDA-drug-shortage-dashboard/',
        scope: '/TFDA-drug-shortage-dashboard/',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
        runtimeCaching: [
          {
            // CR-05：改用 NetworkFirst，確保線上使用者當次載入即取得最新 JSON，
            // 網路失敗或逾時才退回 cache（離線可用）；不再因 StaleWhileRevalidate
            // 先交付舊資料而讓臨床使用者看到陳舊供應狀態。
            urlPattern: ({ url }) => url.pathname.endsWith('supply_status_latest.json'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'shortage-data-v1',
              networkTimeoutSeconds: 5,
              expiration: { maxAgeSeconds: 60 * 60 * 24 * 30 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ url }) => url.origin === 'https://fonts.googleapis.com',
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'google-fonts-stylesheets',
              expiration: { maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ url }) => url.origin === 'https://fonts.gstatic.com',
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-webfonts',
              expiration: { maxAgeSeconds: 60 * 60 * 24 * 365, maxEntries: 30 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  base: '/TFDA-drug-shortage-dashboard/',
})
