import type {
  AdminManagedUser,
  AdminSettings,
  ChatRequest,
  ChatStreamEvent,
  Conversation,
  Message,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
  SetupStatus,
  User,
} from './types'

const API_BASE = 'http://127.0.0.1:8000/api'

type RequestOptions = {
  method?: string
  token?: string | null
  body?: unknown
}

type ValidationErrorItem = {
  loc?: Array<string | number>
  msg?: string
  type?: string
}

function isValidationErrorItem(value: unknown): value is ValidationErrorItem {
  if (!value || typeof value !== 'object') return false
  const item = value as ValidationErrorItem
  return Array.isArray(item.loc) || typeof item.msg === 'string' || typeof item.type === 'string'
}

export function formatApiErrorDetail(detail: unknown, fallback = '请求失败'): string {
  if (typeof detail === 'string') return detail || fallback
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!isValidationErrorItem(item)) return typeof item === 'string' ? item : JSON.stringify(item)
      const field = item.loc?.filter((part) => part !== 'body').join('.')
      return [field, item.msg].filter(Boolean).join(': ') || item.type || JSON.stringify(item)
    })
    return messages.filter(Boolean).join('\n') || fallback
  }
  if (detail && typeof detail === 'object') {
    return JSON.stringify(detail)
  }
  return fallback
}

async function responseErrorMessage(response: Response, fallback = '请求失败'): Promise<string> {
  let text = ''
  try {
    text = await response.text()
  } catch {
    return fallback
  }
  if (!text) return fallback
  try {
    const data = JSON.parse(text) as { detail?: unknown }
    return formatApiErrorDetail(data.detail, fallback)
  } catch {
    return text
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? 'GET',
    headers: {
      'Content-Type': 'application/json',
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  })

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response))
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

async function parseNdjsonStream<T>(response: Response, onChunk: (chunk: T) => void) {
  const reader = response.body?.getReader()
  if (!reader) {
    throw new Error('流式响应不可用')
  }

  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      onChunk(JSON.parse(trimmed) as T)
    }

    if (done) {
      if (buffer.trim()) {
        onChunk(JSON.parse(buffer.trim()) as T)
      }
      break
    }
  }
}

function normalizeMessage(message: Message): Message {
  if (Array.isArray(message.parts) && message.parts.length > 0) {
    return message
  }

  if (
    typeof message.content === 'object' &&
    message.content !== null &&
    !Array.isArray(message.content) &&
    Array.isArray(message.content.parts)
  ) {
    return { ...message, parts: message.content.parts }
  }

  return message
}

function normalizeChatStreamEvent(event: ChatStreamEvent): ChatStreamEvent {
  if (event.type !== 'done') {
    return event
  }

  return {
    ...event,
    messages: event.messages.map(normalizeMessage),
  }
}

export const api = {
  health: () => request<{ status: string }>('/health'),
  setupStatus: () => request<SetupStatus>('/setup/status'),
  setupAdmin: (username: string, password: string) =>
    request<{ token: string; user: User }>('/setup/admin', {
      method: 'POST',
      body: { username, password },
    }),
  login: (username: string, password: string) =>
    request<{ token: string; user: User }>('/auth/login', {
      method: 'POST',
      body: { username, password },
    }),
  authSettings: () => request<AdminSettings>('/auth/settings'),
  register: (username: string, password: string) =>
    request<{ token: string; user: User }>('/auth/register', {
      method: 'POST',
      body: { username, password },
    }),
  me: (token: string) => request<User>('/auth/me', { token }),
  logout: (token: string) => request<{ status: string }>('/auth/logout', { method: 'POST', token }),
  listProviders: (token: string) => request<Provider[]>('/providers', { token }),
  listSearchProviders: () => request<SearchProviderAvailability>('/search-providers'),
  listAdminSearchProviders: (token: string) =>
    request<SearchProviderAvailability>('/admin/search-providers', { token }),
  updateAdminSearchProvider: (
    token: string,
    kind: SearchProviderKind,
    body: { api_key: string; is_enabled: boolean },
  ) => request<SearchProviderAvailability[SearchProviderKind]>(`/admin/search-providers/${kind}`, { method: 'PUT', token, body }),
  listAdminProviders: (token: string) => request<Provider[]>('/admin/providers', { token }),
  createProvider: (
    token: string,
    body: {
      name: string
      api_format: string
      api_url: string
      api_key: string
      model_name: string
      supports_thinking: boolean
      supports_vision: boolean
      supports_tool_calling: boolean
      thinking_effort: string
      max_context_window: number
      max_output_tokens: number
      is_enabled: boolean
    },
  ) => request<Provider>('/admin/providers', { method: 'POST', token, body }),
  updateProvider: (
    token: string,
    providerId: number,
    body: {
      name: string
      api_format: string
      api_url: string
      api_key: string
      model_name: string
      supports_thinking: boolean
      supports_vision: boolean
      supports_tool_calling: boolean
      thinking_effort: string
      max_context_window: number
      max_output_tokens: number
      is_enabled: boolean
    },
  ) => request<Provider>(`/admin/providers/${providerId}`, { method: 'PUT', token, body }),
  deleteProvider: (token: string, providerId: number) =>
    request<{ status: string }>(`/admin/providers/${providerId}`, { method: 'DELETE', token }),
  updateAdminProfile: (
    token: string,
    body: { username: string; current_password: string; new_password: string },
  ) => request<User>('/admin/profile', { method: 'PUT', token, body }),
  getAdminSettings: (token: string) => request<AdminSettings>('/admin/settings', { token }),
  updateAdminSettings: (token: string, body: AdminSettings) =>
    request<AdminSettings>('/admin/settings', { method: 'PUT', token, body }),
  listAdminUsers: (token: string) => request<AdminManagedUser[]>('/admin/users', { token }),
  createAdminUser: (
    token: string,
    body: { username: string; password: string; role: 'admin' | 'user'; is_enabled: boolean },
  ) => request<AdminManagedUser>('/admin/users', { method: 'POST', token, body }),
  updateAdminUser: (token: string, userId: number, body: { is_enabled: boolean }) =>
    request<AdminManagedUser>(`/admin/users/${userId}`, { method: 'PUT', token, body }),
  resetAdminUserPassword: (token: string, userId: number, body: { new_password: string }) =>
    request<{ status: string }>(`/admin/users/${userId}/password`, { method: 'PUT', token, body }),
  deleteAdminUser: (token: string, userId: number) =>
    request<{ status: string }>(`/admin/users/${userId}`, { method: 'DELETE', token }),
  listConversations: (token: string) => request<Conversation[]>('/conversations', { token }),
  renameConversation: (token: string, conversationId: number, title: string) =>
    request<Conversation>(`/conversations/${conversationId}`, { method: 'PUT', token, body: { title } }),
  deleteConversation: (token: string, conversationId: number) =>
    request<{ status: string }>(`/conversations/${conversationId}`, { method: 'DELETE', token }),
  getConversationMessages: (token: string, conversationId: number) =>
    request<{ conversation: Conversation; messages: Message[] }>(`/conversations/${conversationId}/messages`, { token }),
  streamMessage: async (
    token: string,
    body: ChatRequest,
    onChunk: (chunk: ChatStreamEvent) => void,
    signal?: AbortSignal,
  ) => {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    })

    if (!response.ok) {
      throw new Error(await responseErrorMessage(response))
    }

    await parseNdjsonStream<ChatStreamEvent>(response, (chunk) => onChunk(normalizeChatStreamEvent(chunk)))
  },
}
