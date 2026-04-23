export type ThinkingEffort = 'low' | 'medium' | 'high' | 'max'

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

export type SetupStatus = {
  needs_admin_setup: boolean
}

export type Provider = {
  id: number
  name: string
  model_name: string
  supports_thinking: boolean
  supports_vision: boolean
  supports_tool_calling: boolean
  thinking_effort: ThinkingEffort
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

export type SearchProviderKind = 'exa' | 'tavily'

export type SearchProviderStatus = {
  is_enabled: boolean
  is_configured: boolean
}

export type SearchProviderAvailability = Record<SearchProviderKind, SearchProviderStatus>

export type ChatRequest = {
  provider_id: number
  conversation_id?: number
  text: string
  enable_thinking: boolean
  enable_search: boolean
  search_provider: SearchProviderKind | null
  effort: string
  attachments: Attachment[]
}

export type TimelinePartKind = 'thinking' | 'tool' | 'answer'

export type TimelinePartStatus = 'running' | 'done' | 'error'

export type TimelinePart = {
  id: string
  kind: TimelinePartKind
  status: TimelinePartStatus
  text?: string
  label?: string
  detail?: string
  output?: string
  tool_name?: string
  input?: string
}

export type Message = {
  id: number
  role: 'user' | 'assistant'
  content: string | Array<Record<string, unknown>> | { parts: TimelinePart[] }
  parts?: TimelinePart[]
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

export type StreamActivity = {
  id: string
  kind: 'thinking' | 'tool'
  label: string
  status: 'running' | 'done' | 'error'
  duration_ms?: number
  detail?: string
  output?: string
}

export type ChatDonePayload = {
  conversation: Conversation
  messages: Message[]
}

export type ChatStreamEvent =
  | { type: 'conversation'; conversation: Partial<Conversation> & Pick<Conversation, 'id' | 'provider_id'> }
  | { type: 'timeline_part_start'; part: TimelinePart }
  | { type: 'timeline_part_delta'; part_id: string; delta: Partial<TimelinePart> }
  | { type: 'timeline_part_end'; part_id: string }
  | { type: 'timeline_part_error'; part_id: string; detail: string }
  | { type: 'text_delta'; delta: string }
  | { type: 'thinking_delta'; delta: string }
  | { type: 'activity'; activity: StreamActivity }
  | ({ type: 'done' } & ChatDonePayload)
  | { type: 'error'; detail: string }
  | { type: 'usage'; usage: Record<string, unknown> }
