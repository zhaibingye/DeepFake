type FrontendRuntimeConfig = {
  backendUrl?: string
  apiBaseUrl?: string
}

declare global {
  interface Window {
    DEEPFAKE_CONFIG?: FrontendRuntimeConfig
  }
}

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000'

function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

function getRuntimeConfig(): FrontendRuntimeConfig | undefined {
  if (typeof window === 'undefined') return undefined
  return window.DEEPFAKE_CONFIG
}

export function getApiBaseUrl(config: FrontendRuntimeConfig | undefined = getRuntimeConfig()): string {
  const apiBaseUrl = config?.apiBaseUrl?.trim()
  if (apiBaseUrl) return normalizeUrl(apiBaseUrl)

  const backendUrl = normalizeUrl(config?.backendUrl?.trim() || DEFAULT_BACKEND_URL)
  return backendUrl.endsWith('/api') ? backendUrl : `${backendUrl}/api`
}

export const API_BASE_URL = getApiBaseUrl()
