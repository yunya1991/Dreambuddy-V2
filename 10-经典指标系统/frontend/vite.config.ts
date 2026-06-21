import { defineConfig, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const FIXED_PROXY_TARGET = 'http://127.0.0.1:8092'

export default defineConfig(() => {

  const uiPort = 4000
  const timeout = 60000

  const mkProxy = (rewriteApi: boolean): ProxyOptions => {
    const base: ProxyOptions = {
      target: FIXED_PROXY_TARGET,
      changeOrigin: true,
      secure: false,
      timeout,
    }
    if (rewriteApi) {
      base.rewrite = (path: string) => path.replace(/^\/api/, '')
    }
    return base
  }

  return {
    plugins: [react()],
    define: {
      'import.meta.env.VITE_BUILD_STAMP': JSON.stringify(new Date().toISOString()),
    },
    server: {
      host: '127.0.0.1',
      port: uiPort,
      strictPort: true,
      proxy: {
        '/api': mkProxy(true),
        '/automation': mkProxy(false),
      },
    },
    preview: {
      host: '127.0.0.1',
      port: uiPort,
      strictPort: true,
      proxy: {
        '/api': mkProxy(true),
        '/automation': mkProxy(false),
      },
    },
  }
})
