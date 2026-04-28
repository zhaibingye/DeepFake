import type { ProviderApiFormat, ThinkingEffort } from '../../types'

export type ProviderFormState = {
  name: string
  api_format: ProviderApiFormat
  api_url: string
  api_key: string
  model_name: string
  supports_thinking: boolean
  supports_vision: boolean
  supports_tool_calling: boolean
  thinking_effort: ThinkingEffort
  max_context_window: number
  max_output_tokens: number
  is_enabled: boolean
}

export const defaultProviderForm: ProviderFormState = {
  name: '',
  api_format: 'anthropic_messages',
  api_url: '',
  api_key: '',
  model_name: '',
  supports_thinking: true,
  supports_vision: false,
  supports_tool_calling: false,
  thinking_effort: 'high',
  max_context_window: 256000,
  max_output_tokens: 32000,
  is_enabled: true,
}
