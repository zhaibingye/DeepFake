import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function getManualChunk(id: string) {
  if (!id.includes('node_modules')) {
    return undefined
  }

  if (id.includes('/node_modules/react/') || id.includes('/node_modules/react-dom/') || id.includes('/node_modules/scheduler/')) {
    return 'react-vendor'
  }

  if (id.includes('/node_modules/lucide-react/')) {
    return 'icons'
  }

  if (
    /\/node_modules\/(katex|react-markdown|remark-|rehype-|mdast-|hast-|micromark|unified|unist-|vfile|property-information|space-separated-tokens|comma-separated-tokens|html-url-attributes|decode-named-character-reference|character-entities|trim-lines|zwitch|devlop|escape-string-regexp)\//.test(id)
  ) {
    return 'markdown'
  }

  return 'vendor'
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: getManualChunk,
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
})
