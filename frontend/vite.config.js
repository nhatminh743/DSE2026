import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Keep the precomputed showcase in one repository folder while exposing its
  // contents at /data in both the dev server and production build.
  publicDir: '../static_showcase',
  server: {
    port: 3000
  }
})
