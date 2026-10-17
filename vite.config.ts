import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import app from './app.json';

const server = `http://127.0.0.1:${app.port}`;

export default defineConfig({
  plugins: [react(), { name: 'app-name', transformIndexHtml: html => html.replace('%APP_NAME%', app.name) }],
  server: {
    port: app.devPort,
    strictPort: true,
    proxy: {
      '/api': {
        target: server,
        changeOrigin: true,
        // The server accepts only its own page, so requests from this one are passed on as its own.
        configure: proxy => proxy.on('proxyReq', (request, incoming) => {
          if (incoming.headers.origin === `http://${incoming.headers.host}`) request.setHeader('Origin', server);
        }),
      },
    },
  },
});
