
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const _showFatalOverlay = (title: string, details: string) => {
  try {
    const id = '__fatal_overlay__'
    const existing = document.getElementById(id)
    if (existing) existing.remove()

    const wrap = document.createElement('div')
    wrap.id = id
    wrap.style.position = 'fixed'
    wrap.style.inset = '0'
    wrap.style.zIndex = '2147483647'
    wrap.style.background = 'rgba(15, 23, 42, 0.92)'
    wrap.style.color = '#e2e8f0'
    wrap.style.padding = '20px'
    wrap.style.fontFamily = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace'
    wrap.style.overflow = 'auto'

    const h = document.createElement('div')
    h.textContent = title
    h.style.fontSize = '14px'
    h.style.fontWeight = '700'
    h.style.marginBottom = '10px'

    const pre = document.createElement('pre')
    pre.textContent = details
    pre.style.whiteSpace = 'pre-wrap'
    pre.style.wordBreak = 'break-word'
    pre.style.fontSize = '12px'
    pre.style.lineHeight = '1.35'
    pre.style.margin = '0'

    const btnRow = document.createElement('div')
    btnRow.style.marginTop = '14px'
    btnRow.style.display = 'flex'
    btnRow.style.gap = '10px'

    const mkBtn = (label: string, onClick: () => void) => {
      const b = document.createElement('button')
      b.type = 'button'
      b.textContent = label
      b.style.border = '1px solid rgba(148, 163, 184, 0.35)'
      b.style.background = 'rgba(2, 6, 23, 0.4)'
      b.style.color = '#e2e8f0'
      b.style.padding = '6px 10px'
      b.style.borderRadius = '6px'
      b.style.cursor = 'pointer'
      b.onclick = onClick
      return b
    }

    btnRow.appendChild(mkBtn('Reload', () => window.location.reload()))
    btnRow.appendChild(mkBtn('Dismiss', () => wrap.remove()))

    wrap.appendChild(h)
    wrap.appendChild(pre)
    wrap.appendChild(btnRow)
    document.body.appendChild(wrap)
  } catch {
    void 0
  }
}

const _installGlobalErrorOverlay = () => {
  if (typeof window === 'undefined') return
  const w = window as unknown as { __overlayInstalled?: boolean }
  if (w.__overlayInstalled) return
  w.__overlayInstalled = true

  window.addEventListener('error', (ev) => {
    const msg = String((ev as ErrorEvent).message ?? 'error')
    const err = (ev as ErrorEvent).error
    const stack = err && typeof err === 'object' && 'stack' in err ? String((err as { stack?: unknown }).stack ?? '') : ''
    _showFatalOverlay('Frontend Runtime Error', [msg, stack].filter(Boolean).join('\n'))
  })

  window.addEventListener('unhandledrejection', (ev) => {
    const r = (ev as PromiseRejectionEvent).reason
    const msg = r instanceof Error ? (r.stack || r.message) : typeof r === 'string' ? r : JSON.stringify(r)
    _showFatalOverlay('Unhandled Promise Rejection', String(msg ?? 'rejection'))
  })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      retry: (failureCount, error) => {
        const status = (error as { response?: { status?: number } } | null | undefined)?.response?.status;
        if (status === 429) return false;
        if (typeof status === 'number' && status >= 400 && status < 500) return false;
        return failureCount < 2;
      },
      retryDelay: (attemptIndex) => Math.min(30_000, 1_000 * 2 ** attemptIndex),
    },
  },
})

_installGlobalErrorOverlay()

try {
  const rootEl = document.getElementById('root')
  if (!rootEl) {
    _showFatalOverlay('Frontend Bootstrap Error', 'Missing #root element in index.html')
  } else {
    createRoot(rootEl).render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    )
  }
} catch (e) {
  const msg = e instanceof Error ? (e.stack || e.message) : String(e)
  _showFatalOverlay('Frontend Bootstrap Error', msg)
}
