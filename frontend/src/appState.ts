import type { Attachment, Provider, ProviderApiFormat, ThinkingEffort } from './types'

export type AuthMode = 'login' | 'register'

export const standardThinkingEffortOptions: ThinkingEffort[] = ['low', 'medium', 'high', 'max']
export const openAiChatThinkingEffortOptions: ThinkingEffort[] = ['low', 'medium', 'high']
export const openAiResponsesThinkingEffortOptions: ThinkingEffort[] = ['low', 'medium', 'high', 'xhigh']

export function getThinkingEffortOptions(apiFormat?: ProviderApiFormat): ThinkingEffort[] {
  if (apiFormat === 'openai_chat') return openAiChatThinkingEffortOptions
  if (apiFormat === 'openai_responses') return openAiResponsesThinkingEffortOptions
  return standardThinkingEffortOptions
}

export function normalizeThinkingEffort(effort: string, apiFormat?: ProviderApiFormat): ThinkingEffort {
  if (apiFormat === 'openai_chat' && effort === 'max') return 'high'
  if (apiFormat === 'openai_chat' && effort === 'xhigh') return 'high'
  if (apiFormat === 'openai_responses' && effort === 'max') return 'xhigh'
  if (apiFormat !== 'openai_responses' && effort === 'xhigh') return 'max'
  const options = getThinkingEffortOptions(apiFormat)
  if (options.includes(effort as ThinkingEffort)) return effort as ThinkingEffort
  return 'high'
}

export function resolveAuthMode(authMode: AuthMode, allowRegistration: boolean): AuthMode {
  if (!allowRegistration && authMode === 'register') {
    return 'login'
  }
  return authMode
}

export function constrainProviderState(
  state: {
    effort: ThinkingEffort
    enableThinking: boolean
    enableSearch: boolean
    attachments: Attachment[]
  },
  provider: Provider | null,
) {
  if (!provider) {
    return state
  }
  const supportsNativeToolCalling =
    provider.supports_tool_calling
    && (
      provider.api_format === 'anthropic_messages'
      || provider.api_format === 'openai_chat'
      || provider.api_format === 'openai_responses'
      || provider.api_format === 'gemini'
    )

  return {
    effort: normalizeThinkingEffort(provider.thinking_effort, provider.api_format),
    enableThinking: provider.supports_thinking ? state.enableThinking : false,
    enableSearch: supportsNativeToolCalling ? state.enableSearch : false,
    attachments:
      provider.supports_vision || state.attachments.length === 0 ? state.attachments : [],
  }
}
