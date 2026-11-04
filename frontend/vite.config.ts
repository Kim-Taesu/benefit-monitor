import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
export default defineConfig({
  plugins: [vue()], base: '/benefit-monitor/', publicDir: false,
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
