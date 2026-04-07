import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Split React and React Router into separate chunk
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // Split react-markdown and its deps (used for document rendering)
          'vendor-markdown': ['react-markdown'],
        },
      },
    },
    // Increase warning limit since we're intentionally bundling job data
    chunkSizeWarningLimit: 1200,
  },
})
