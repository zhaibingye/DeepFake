import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { AdminPage } from './admin/AdminPage'
import { AuthPage } from './auth/AuthPage'
import { ChatPage } from './chat/ChatPage'
import { defaultProviderForm } from './admin/providerForm'
import { buildSearchProviderForms } from './admin/controller'
import type { AdminManagedUser, Conversation, Provider, User } from '../types'

function makeProvider(overrides: Partial<Provider> = {}): Provider {
  return {
    id: 1,
    name: 'Test Provider',
    api_format: 'anthropic_messages',
    model_name: 'claude-test',
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

function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    username: 'admin',
    role: 'admin',
    is_enabled: true,
    ...overrides,
  }
}

describe('presentational page components', () => {
  it('renders the auth surface with stable setup messaging', () => {
    const html = renderToStaticMarkup(
      <AuthPage
        authMode="login"
        effectiveAuthMode="login"
        authUsername=""
        authPassword=""
        setupPasswordConfirm=""
        authError=""
        loadingAuth={false}
        publicAuthSettings={{ allow_registration: false }}
        setupStatus={{ needs_admin_setup: true }}
        setupStatusLoaded
        setAuthMode={vi.fn()}
        setAuthUsername={vi.fn()}
        setAuthPassword={vi.fn()}
        setSetupPasswordConfirm={vi.fn()}
        onSubmit={vi.fn()}
      />,
    )

    expect(html).toContain('setup-shell')
    expect(html).toContain('创建第一个管理员')
    expect(html).toContain('确认密码')
    expect(html).toContain('创建管理员并进入')
  })

  it('renders the admin user page without changing existing labels', () => {
    const users: AdminManagedUser[] = [
      {
        id: 2,
        username: 'member',
        role: 'user',
        is_enabled: true,
        created_at: '2026-04-23T00:00:00Z',
      },
    ]

    const html = renderToStaticMarkup(
      <AdminPage
        adminSection="users"
        adminProviders={[makeProvider()]}
        adminSearchProviders={{
          exa: { kind: 'exa', name: 'Exa', is_enabled: true, is_configured: true, api_key_masked: '未设置（可选）' },
          tavily: { kind: 'tavily', name: 'Tavily', is_enabled: false, is_configured: false, api_key_masked: '未设置' },
        }}
        adminUsers={users}
        adminSettings={{ allow_registration: true }}
        adminProfile={{ username: 'admin', current_password: '', new_password: '' }}
        adminProfileMessage=""
        userForm={{ username: '', password: '', role: 'user', is_enabled: true }}
        userSearch=""
        userAdminMessage=""
        userAdminError={false}
        editingProviderId={null}
        providerForm={defaultProviderForm}
        providerError=""
        providerSuccess=""
        searchProviderForms={buildSearchProviderForms({
          exa: { is_enabled: true, is_configured: true },
          tavily: { is_enabled: false, is_configured: false },
        })}
        searchProviderMessage=""
        searchProviderError={false}
        providerApiUrlPlaceholder="https://.../anthropic/v1"
        thinkingEffortOptions={['low', 'medium', 'high', 'max']}
        filteredAdminUsers={users}
        navigateToChat={vi.fn()}
        handleLogout={vi.fn()}
        navigateToAdminSection={vi.fn()}
        onSubmitAdminProfile={vi.fn()}
        onSubmitProvider={vi.fn()}
        onSubmitSearchProvider={vi.fn()}
        onSubmitAdminUser={vi.fn()}
        setAdminProfile={vi.fn()}
        setProviderForm={vi.fn()}
        setSearchProviderForms={vi.fn()}
        cancelEditingProvider={vi.fn()}
        editProvider={vi.fn()}
        removeProvider={vi.fn()}
        toggleAllowRegistration={vi.fn()}
        setUserForm={vi.fn()}
        setUserSearch={vi.fn()}
        resetAdminUserPassword={vi.fn()}
        toggleUserEnabled={vi.fn()}
        removeAdminUser={vi.fn()}
      />,
    )

    expect(html).toContain('admin-subnav')
    expect(html).toContain('注册与创建')
    expect(html).toContain('手动添加用户')
    expect(html).toContain('member')
  })

  it('renders one supports-vision checkbox in the admin provider form', () => {
    const html = renderToStaticMarkup(
      <AdminPage
        adminSection="providers"
        adminProviders={[makeProvider()]}
        adminSearchProviders={{
          exa: { kind: 'exa', name: 'Exa', is_enabled: true, is_configured: true, api_key_masked: '未设置（可选）' },
          tavily: { kind: 'tavily', name: 'Tavily', is_enabled: false, is_configured: false, api_key_masked: '未设置' },
        }}
        adminUsers={[]}
        adminSettings={{ allow_registration: true }}
        adminProfile={{ username: 'admin', current_password: '', new_password: '' }}
        adminProfileMessage=""
        userForm={{ username: '', password: '', role: 'user', is_enabled: true }}
        userSearch=""
        userAdminMessage=""
        userAdminError={false}
        editingProviderId={null}
        providerForm={{ ...defaultProviderForm, supports_vision: true }}
        providerError=""
        providerSuccess=""
        searchProviderForms={buildSearchProviderForms({
          exa: { is_enabled: true, is_configured: true },
          tavily: { is_enabled: false, is_configured: false },
        })}
        searchProviderMessage=""
        searchProviderError={false}
        providerApiUrlPlaceholder="https://.../anthropic/v1"
        thinkingEffortOptions={['low', 'medium', 'high', 'max']}
        filteredAdminUsers={[]}
        navigateToChat={vi.fn()}
        handleLogout={vi.fn()}
        navigateToAdminSection={vi.fn()}
        onSubmitAdminProfile={vi.fn()}
        onSubmitProvider={vi.fn()}
        onSubmitSearchProvider={vi.fn()}
        onSubmitAdminUser={vi.fn()}
        setAdminProfile={vi.fn()}
        setProviderForm={vi.fn()}
        setSearchProviderForms={vi.fn()}
        cancelEditingProvider={vi.fn()}
        editProvider={vi.fn()}
        removeProvider={vi.fn()}
        toggleAllowRegistration={vi.fn()}
        setUserForm={vi.fn()}
        setUserSearch={vi.fn()}
        resetAdminUserPassword={vi.fn()}
        toggleUserEnabled={vi.fn()}
        removeAdminUser={vi.fn()}
      />,
    )

    expect(html.match(/支持视觉/g)).toHaveLength(1)
    expect(html).toContain('模型能力')
    expect(html).toContain('供应商状态')
    expect(html).toContain('启用供应商')
    expect(html).toContain('OpenAI Responses')
    expect(html).not.toContain('保存 Exa 配置')
    expect(html).not.toContain('保存 Tavily 配置')
  })

  it('renders search MCP settings on the dedicated admin subpage', () => {
    const html = renderToStaticMarkup(
      <AdminPage
        adminSection="search-mcp"
        adminProviders={[makeProvider()]}
        adminSearchProviders={{
          exa: { kind: 'exa', name: 'Exa', is_enabled: true, is_configured: true, api_key_masked: '未设置（可选）' },
          tavily: { kind: 'tavily', name: 'Tavily', is_enabled: false, is_configured: false, api_key_masked: '未设置' },
        }}
        adminUsers={[]}
        adminSettings={{ allow_registration: true }}
        adminProfile={{ username: 'admin', current_password: '', new_password: '' }}
        adminProfileMessage=""
        userForm={{ username: '', password: '', role: 'user', is_enabled: true }}
        userSearch=""
        userAdminMessage=""
        userAdminError={false}
        editingProviderId={null}
        providerForm={defaultProviderForm}
        providerError=""
        providerSuccess=""
        searchProviderForms={buildSearchProviderForms({
          exa: { is_enabled: true, is_configured: true },
          tavily: { is_enabled: false, is_configured: false },
        })}
        searchProviderMessage=""
        searchProviderError={false}
        providerApiUrlPlaceholder="https://.../anthropic/v1"
        thinkingEffortOptions={['low', 'medium', 'high', 'max']}
        filteredAdminUsers={[]}
        navigateToChat={vi.fn()}
        handleLogout={vi.fn()}
        navigateToAdminSection={vi.fn()}
        onSubmitAdminProfile={vi.fn()}
        onSubmitProvider={vi.fn()}
        onSubmitSearchProvider={vi.fn()}
        onSubmitAdminUser={vi.fn()}
        setAdminProfile={vi.fn()}
        setProviderForm={vi.fn()}
        setSearchProviderForms={vi.fn()}
        cancelEditingProvider={vi.fn()}
        editProvider={vi.fn()}
        removeProvider={vi.fn()}
        toggleAllowRegistration={vi.fn()}
        setUserForm={vi.fn()}
        setUserSearch={vi.fn()}
        resetAdminUserPassword={vi.fn()}
        toggleUserEnabled={vi.fn()}
        removeAdminUser={vi.fn()}
      />,
    )

    expect(html).toContain('搜索 MCP 管理')
    expect(html).toContain('联网搜索')
    expect(html).toContain('保存 Exa 配置')
    expect(html).toContain('保存 Tavily 配置')
  })

  it('renders the chat shell and composer with the existing prompt text', () => {
    const provider = makeProvider()
    const conversation: Conversation = {
      id: 9,
      title: '新对话',
      provider_id: provider.id,
      provider_name: provider.name,
      model_name: provider.model_name,
      created_at: '2026-04-23T00:00:00Z',
      updated_at: '2026-04-23T00:00:00Z',
    }
    const html = renderToStaticMarkup(
      <ChatPage
        sidebarCollapsed={false}
        chatLoading={false}
        conversations={[conversation]}
        activeConversationId={conversation.id}
        currentConversation={conversation}
        currentConversationProvider={provider}
        selectedProvider={provider}
        selectedProviderId={provider.id}
        providers={[provider]}
        user={makeUser()}
        hasVisibleConversation={false}
        messages={[]}
        pendingUserMessage={null}
        streamingTimeline={{
          parts: [],
          revision: '',
          expandedById: {},
          setExpanded: vi.fn(),
        }}
        messageEndRef={{ current: null }}
        fileInputRef={{ current: null }}
        input=""
        attachments={[]}
        enableThinking
        enableSearch={false}
        searchProvider="exa"
        searchProviders={null}
        effort="high"
        thinkingEffortOptions={['low', 'medium', 'high', 'max']}
        chatError=""
        selectedProviderSupportsToolCalling
        toggleSidebar={vi.fn()}
        startNewConversation={vi.fn()}
        openConversation={vi.fn()}
        renameConversation={vi.fn()}
        removeConversation={vi.fn()}
        navigateToAdmin={vi.fn()}
        handleLogout={vi.fn()}
        onSubmit={vi.fn()}
        setInput={vi.fn()}
        handleComposerKeyDown={vi.fn()}
        removeAttachment={vi.fn()}
        setEnableThinking={vi.fn()}
        setEnableSearch={vi.fn()}
        setChatError={vi.fn()}
        setSearchProvider={vi.fn()}
        applyProviderSelection={vi.fn()}
        triggerFileSelect={vi.fn()}
        stopStreaming={vi.fn()}
        handleFileChange={vi.fn()}
        setEffort={vi.fn()}
      />,
    )

    expect(html).toContain('chat-shell')
    expect(html).toContain('今天有什么可以帮到你？')
    expect(html).toContain(`给 ${provider.name} 发送消息`)
  })
})
