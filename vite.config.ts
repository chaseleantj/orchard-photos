import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import app from './app.json';

export default defineConfig({
  plugins: [react(), { name: 'app-name', transformIndexHtml: html => html.replace('%APP_NAME%', app.name) }],
  server: { port: app.devPort, strictPort: true, proxy: { '/api': `http://127.0.0.1:${app.port}` } },
});
