import { describe, expect, it } from 'vitest'

import {
  constrainProviderState,
  getThinkingEffortOptions,
  normalizeThinkingEffort,
  resolveAuthMode,
} from './appState'
import type { Provider } from './types'

function makeProvider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: 1,
    name: 'Test Provider',
    api_format: 'anthropic_messages',
    model_name: 'model',
    supports_thinking: true,
    supports_vision: true,
    supports_tool_calling: true,
    thinking_effort: 'high',
    max_context_window: 256000,
    max_output_tokens: 32000,
    is_enabled: true,
    created_at: '2026-04-23T00:00:00Z',
    updated_at: '2026-04-23T00:00:00Z',
    ...overrides,
  }
}

describe('app state helpers', () => {
  it('falls back to login mode when registration is disabled', () => {
    expect(resolveAuthMode('register', false)).toBe('login')
    expect(resolveAuthMode('login', false)).toBe('login')
  })

  it('resets composer state to match provider capabilities', () => {
    const nextState = constrainProviderState(
      {
        effort: 'low',
        enableThinking: true,
        enableSearch: true,
        attachments: [{ name: 'img.png', media_type: 'image/png', data: 'abc' }],
      },
      makeProvider({
        supports_thinking: false,
        supports_vision: false,
        supports_tool_calling: false,
        thinking_effort: 'max',
      }),
    )

    expect(nextState).toEqual({
      effort: 'max',
      enableThinking: false,
      enableSearch: false,
      attachments: [],
    })
  })

  it('keeps compatible composer state when provider supports the active features', () => {
    const attachments = [{ name: 'img.png', media_type: 'image/png', data: 'abc' }]

    expect(
      constrainProviderState(
        {
          effort: 'low',
          enableThinking: true,
          enableSearch: true,
          attachments,
        },
        makeProvider(),
      ),
    ).toEqual({
      effort: 'high',
      enableThinking: true,
      enableSearch: true,
      attachments,
    })
  })

  it('keeps search enabled for OpenAI Responses providers that support tool calling', () => {
    expect(
      constrainProviderState(
        {
          effort: 'low',
          enableThinking: true,
          enableSearch: true,
          attachments: [],
        },
        makeProvider({ api_format: 'openai_responses', supports_tool_calling: true }),
      ),
    ).toEqual({
      effort: 'high',
      enableThinking: true,
      enableSearch: true,
      attachments: [],
    })
  })

  it('normalizes unknown thinking effort values', () => {
    expect(normalizeThinkingEffort('weird')).toBe('high')
  })

  it('limits OpenAI Chat thinking effort options to low medium high', () => {
    expect(getThinkingEffortOptions('openai_chat')).toEqual(['low', 'medium', 'high'])
    expect(normalizeThinkingEffort('max', 'openai_chat')).toBe('high')
  })

  it('uses xhigh as the highest OpenAI Responses thinking effort', () => {
    expect(getThinkingEffortOptions('openai_responses')).toEqual(['low', 'medium', 'high', 'xhigh'])
    expect(normalizeThinkingEffort('xhigh', 'openai_responses')).toBe('xhigh')
    expect(normalizeThinkingEffort('max', 'openai_responses')).toBe('xhigh')
  })
})
