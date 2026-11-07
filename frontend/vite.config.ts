import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';
const page = (name: string) => fileURLToPath(new URL(name, import.meta.url));
export default defineConfig({
  plugins: [vue()], base: '/benefit-monitor/', publicDir: false,
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false,
    rollupOptions: { input: { index: page('./index.html'), admin: page('./admin.html') } } },
});
