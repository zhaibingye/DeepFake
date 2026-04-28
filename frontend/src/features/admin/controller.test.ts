import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../api'
import type { Provider } from '../../types'
import { defaultProviderForm, type ProviderFormState } from './providerForm'
import { submitProviderState, submitSearchProviderState } from './controller'

vi.mock('../../api', () => ({
  api: {
    createProvider: vi.fn(),
    updateAdminSearchProvider: vi.fn(),
    updateProvider: vi.fn(),
  },
}))

function makeProvider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: 1,
    name: 'Vision Provider',
    api_format: 'anthropic_messages',
    model_name: 'claude-vision',
    supports_thinking: true,
    supports_vision: true,
    supports_tool_calling: false,
    thinking_effort: 'high',
    max_context_window: 256000,
    max_output_tokens: 32000,
    is_enabled: true,
    created_at: '2026-04-23T00:00:00Z',
    updated_at: '2026-04-23T00:00:00Z',
    ...overrides,
  }
}

describe('admin provider controller', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('creates providers with supports_vision enabled without using the error path', async () => {
    const providerForm: ProviderFormState = {
      ...defaultProviderForm,
      name: 'Vision Provider',
      api_format: 'anthropic_messages',
      api_url: 'https://example.test/v1',
      api_key: 'test-key',
      model_name: 'claude-vision',
      supports_vision: true,
    }
    const setProviderError = vi.fn()
    const setProviderSuccess = vi.fn()
    const setProviderForm = vi.fn()
    const setEditingProviderId = vi.fn()
    const refreshAfterSave = vi.fn().mockResolvedValue(undefined)

    vi.mocked(api.createProvider).mockResolvedValue(makeProvider())

    await submitProviderState({
      token: 'admin-token',
      editingProviderId: null,
      providerForm,
      setProviderError,
      setProviderSuccess,
      setProviderForm,
      setEditingProviderId,
      refreshAfterSave,
    })

    expect(api.createProvider).toHaveBeenCalledWith('admin-token', providerForm)
    expect(vi.mocked(api.createProvider).mock.calls[0]?.[1]).toMatchObject({
      supports_vision: true,
    })
    expect(api.updateProvider).not.toHaveBeenCalled()
    expect(setProviderError.mock.calls).toEqual([['']])
    expect(setProviderSuccess.mock.calls).toEqual([[''], ['供应商已添加']])
    expect(setProviderForm).toHaveBeenCalledWith(defaultProviderForm)
    expect(setEditingProviderId).toHaveBeenCalledWith(null)
    expect(refreshAfterSave).toHaveBeenCalled()
  })

  it('saves admin search provider config and clears the typed key after success', async () => {
    const setAdminSearchProviders = vi.fn()
    const setSearchProviderForms = vi.fn()
    const setMessage = vi.fn()
    const setError = vi.fn()

    vi.mocked(api.updateAdminSearchProvider).mockResolvedValue({
      kind: 'exa',
      name: 'Exa',
      is_enabled: false,
      is_configured: true,
      api_key_masked: '已配置',
    })

    await submitSearchProviderState({
      token: 'admin-token',
      kind: 'exa',
      form: { api_key: 'exa-key', is_enabled: false },
      setAdminSearchProviders,
      setSearchProviderForms,
      setMessage,
      setError,
    })

    expect(api.updateAdminSearchProvider).toHaveBeenCalledWith('admin-token', 'exa', {
      api_key: 'exa-key',
      is_enabled: false,
    })
    expect(setMessage.mock.calls[0]).toEqual([''])
    expect(setError.mock.calls[0]).toEqual([false])
    expect(setAdminSearchProviders).toHaveBeenCalled()
    expect(setSearchProviderForms).toHaveBeenCalled()
    expect(setMessage.mock.calls.at(-1)).toEqual(['Exa 搜索配置已保存'])
  })
})
