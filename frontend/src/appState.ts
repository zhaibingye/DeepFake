import type { Attachment, Provider, ThinkingEffort } from './types'

export type AuthMode = 'login' | 'register'

const thinkingEffortOptions: ThinkingEffort[] = ['low', 'medium', 'high', 'max']

export function normalizeThinkingEffort(effort: string): ThinkingEffort {
  if (thinkingEffortOptions.includes(effort as ThinkingEffort)) return effort as ThinkingEffort
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

  return {
    effort: normalizeThinkingEffort(provider.thinking_effort),
    enableThinking: provider.supports_thinking ? state.enableThinking : false,
    enableSearch: provider.supports_tool_calling ? state.enableSearch : false,
    attachments:
      provider.supports_vision || state.attachments.length === 0 ? state.attachments : [],
  }
}
