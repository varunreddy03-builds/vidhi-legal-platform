import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { queryClient } from './lib/queryClient'
import { ThemeProvider } from './lib/theme'
import { I18nProvider } from './lib/i18n/I18nProvider'
import ErrorBoundary from './components/ErrorBoundary'
import ServerGate from './components/native/ServerGate'

// The service worker only enables installing the app and reminder notifications; it caches nothing (see public/sw.js).
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => void navigator.serviceWorker.register('/sw.js').catch(() => undefined))
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <ErrorBoundary>
            <ServerGate>
              <BrowserRouter>
                <App />
              </BrowserRouter>
            </ServerGate>
          </ErrorBoundary>
        </QueryClientProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
)
