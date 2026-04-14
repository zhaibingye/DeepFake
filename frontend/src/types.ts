export type User = {
  id: number
  username: string
  role: 'admin' | 'user'
  is_enabled: boolean
}

export type AdminManagedUser = {
  id: number
  username: string
  role: 'admin' | 'user'
  is_enabled: boolean
  created_at: string
}

export type AdminSettings = {
  allow_registration: boolean
}

export type Provider = {
  id: number
  name: string
  model_name: string
  supports_thinking: boolean
  supports_vision: boolean
  thinking_effort: 'low' | 'medium' | 'high' | 'max'
  max_context_window: number
  max_output_tokens: number
  is_enabled: boolean
  created_at: string
  updated_at: string
  api_key_masked?: string
}

export type Attachment = {
  name: string
  media_type: string
  data: string
}

export type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string | Array<Record<string, unknown>>
  thinking_text: string
  created_at: string
}

export type Conversation = {
  id: number
  title: string
  provider_id: number
  provider_name?: string
  model_name?: string
  created_at: string
  updated_at: string
}
