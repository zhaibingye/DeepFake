import { Bot, LayoutDashboard, LogOut, Search, Settings, Shield, Sparkles, UserRound } from 'lucide-react'

import type { ProviderApiFormat, ThinkingEffort } from '../../types'
import type {
  AdminManagedUser,
  AdminSettings,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
} from '../../types'
import type { ProviderFormState } from './providerForm'
import type { SearchProviderFormState } from './controller'
import { normalizeThinkingEffort } from '../../appState'
import { formatDateTime } from '../../utils'

export type AdminSection = 'overview' | 'providers' | 'search-mcp' | 'users'

type ProviderCapabilityField = keyof Pick<
  ProviderFormState,
  'supports_thinking' | 'supports_vision' | 'supports_tool_calling'
>

const providerCapabilities: ReadonlyArray<{
  field: ProviderCapabilityField
  checkboxLabel: string
  chipLabel: string
}> = [
  { field: 'supports_thinking', checkboxLabel: '支持思考', chipLabel: '思考' },
  { field: 'supports_vision', checkboxLabel: '支持视觉', chipLabel: '视觉' },
  { field: 'supports_tool_calling', checkboxLabel: '支持工具调用', chipLabel: '工具调用' },
]

const providerApiFormatLabels: Record<ProviderApiFormat, string> = {
  anthropic_messages: 'Anthropic Messages',
  openai_chat: 'OpenAI Chat',
  deepseek_chat: 'DeepSeek Chat',
  siliconflow_chat: 'SiliconFlow Chat',
  openai_responses: 'OpenAI Responses',
  gemini: 'Gemini',
}

type AdminProfileState = {
  username: string
  current_password: string
  new_password: string
}

type AdminUserFormState = {
  username: string
  password: string
  role: 'admin' | 'user'
  is_enabled: boolean
}

type AdminPageProps = {
  adminSection: AdminSection
  adminProviders: Provider[]
  adminSearchProviders: SearchProviderAvailability | null
  adminUsers: AdminManagedUser[]
  adminSettings: AdminSettings
  adminProfile: AdminProfileState
  adminProfileMessage: string
  userForm: AdminUserFormState
  userSearch: string
  userAdminMessage: string
  userAdminError: boolean
  editingProviderId: number | null
  providerForm: ProviderFormState
  providerError: string
  providerSuccess: string
  searchProviderForms: Record<SearchProviderKind, SearchProviderFormState>
  searchProviderMessage: string
  searchProviderError: boolean
  providerApiUrlPlaceholder: string
  thinkingEffortOptions: ThinkingEffort[]
  filteredAdminUsers: AdminManagedUser[]
  navigateToChat: () => void
  handleLogout: () => void
  navigateToAdminSection: (section: AdminSection) => void
  onSubmitAdminProfile: (event: React.FormEvent<HTMLFormElement>) => void
  onSubmitProvider: (event: React.FormEvent<HTMLFormElement>) => void
  onSubmitSearchProvider: (
    kind: SearchProviderKind,
    event: React.FormEvent<HTMLFormElement>,
  ) => void
  onSubmitAdminUser: (event: React.FormEvent<HTMLFormElement>) => void
  setAdminProfile: React.Dispatch<React.SetStateAction<AdminProfileState>>
  setProviderForm: React.Dispatch<React.SetStateAction<ProviderFormState>>
  setSearchProviderForms: React.Dispatch<
    React.SetStateAction<Record<SearchProviderKind, SearchProviderFormState>>
  >
  cancelEditingProvider: () => void
  editProvider: (provider: Provider) => void
  removeProvider: (provider: Provider) => void
  toggleAllowRegistration: (value: boolean) => void
  setUserForm: React.Dispatch<React.SetStateAction<AdminUserFormState>>
  setUserSearch: (value: string) => void
  resetAdminUserPassword: (targetUser: AdminManagedUser) => void
  toggleUserEnabled: (targetUser: AdminManagedUser) => void
  removeAdminUser: (targetUser: AdminManagedUser) => void
}

export function AdminPage({
  adminSection,
  adminProviders,
  adminSearchProviders,
  adminUsers,
  adminSettings,
  adminProfile,
  adminProfileMessage,
  userForm,
  userSearch,
  userAdminMessage,
  userAdminError,
  editingProviderId,
  providerForm,
  providerError,
  providerSuccess,
  searchProviderForms,
  searchProviderMessage,
  searchProviderError,
  providerApiUrlPlaceholder,
  thinkingEffortOptions,
  filteredAdminUsers,
  navigateToChat,
  handleLogout,
  navigateToAdminSection,
  onSubmitAdminProfile,
  onSubmitProvider,
  onSubmitSearchProvider,
  onSubmitAdminUser,
  setAdminProfile,
  setProviderForm,
  setSearchProviderForms,
  cancelEditingProvider,
  editProvider,
  removeProvider,
  toggleAllowRegistration,
  setUserForm,
  setUserSearch,
  resetAdminUserPassword,
  toggleUserEnabled,
  removeAdminUser,
}: AdminPageProps) {
  const enabledUsersCount = adminUsers.filter((managedUser) => managedUser.is_enabled).length
  const enabledProvidersCount = adminProviders.filter((provider) => provider.is_enabled).length

  const updateProviderCapability = (field: ProviderCapabilityField, checked: boolean) => {
    setProviderForm((prev) => {
      const next = { ...prev }
      next[field] = checked
      return next
    })
  }

  const updateSearchProviderForm = (
    kind: SearchProviderKind,
    patch: Partial<SearchProviderFormState>,
  ) => {
    setSearchProviderForms((prev) => ({
      ...prev,
      [kind]: {
        ...prev[kind],
        ...patch,
      },
    }))
  }

  return (
    <div className="admin-page">
      <header className="admin-topbar">
        <div className="admin-topbar-left">
          <div className="brand-mark solid"><Shield size={18} /></div>
          <div>
            <h2>管理员后台</h2>
            <p>把系统配置拆分到清晰的二级页面，减少信息拥挤。</p>
          </div>
        </div>
        <div className="admin-topbar-actions">
          <button className="ghost-btn" onClick={navigateToChat} type="button">
            <Bot size={16} />
            返回聊天
          </button>
          <button className="ghost-btn" onClick={handleLogout} type="button">
            <LogOut size={16} />
            退出登录
          </button>
        </div>
      </header>

      <nav className="admin-subnav">
        <button className={adminSection === 'overview' ? 'admin-subnav-btn active' : 'admin-subnav-btn'} onClick={() => navigateToAdminSection('overview')} type="button">
          <Settings size={16} />
          概览
        </button>
        <button className={adminSection === 'providers' ? 'admin-subnav-btn active' : 'admin-subnav-btn'} onClick={() => navigateToAdminSection('providers')} type="button">
          <Shield size={16} />
          供应商管理
        </button>
        <button className={adminSection === 'search-mcp' ? 'admin-subnav-btn active' : 'admin-subnav-btn'} onClick={() => navigateToAdminSection('search-mcp')} type="button">
          <Search size={16} />
          搜索 MCP 管理
        </button>
        <button className={adminSection === 'users' ? 'admin-subnav-btn active' : 'admin-subnav-btn'} onClick={() => navigateToAdminSection('users')} type="button">
          <UserRound size={16} />
          用户管理
        </button>
      </nav>

      <main className="admin-main">
        {adminSection === 'overview' ? (
          <section className="admin-overview-grid">
            <section className="panel-card admin-hero-card">
              <div className="panel-title"><Sparkles size={16} /> 管理概览</div>
              <h3>把高频操作拆开，减少后台页面的视觉负担。</h3>
              <p>供应商维护、用户管理和管理员设置现在分布在不同子页里，修改时更聚焦。</p>
              <div className="admin-metric-grid">
                <div className="admin-metric-card">
                  <strong>{adminProviders.length}</strong>
                  <span>供应商总数</span>
                  <small>{enabledProvidersCount} 个启用中</small>
                </div>
                <div className="admin-metric-card">
                  <strong>{adminUsers.length}</strong>
                  <span>用户总数</span>
                  <small>{enabledUsersCount} 个启用中</small>
                </div>
                <div className="admin-metric-card">
                  <strong>{adminSettings.allow_registration ? '开启' : '关闭'}</strong>
                  <span>注册状态</span>
                  <small>{adminSettings.allow_registration ? '允许普通用户注册' : '仅管理员手动创建'}</small>
                </div>
              </div>
              <div className="action-row">
                <button className="primary-btn" onClick={() => navigateToAdminSection('providers')} type="button">去管理供应商</button>
                <button className="ghost-btn" onClick={() => navigateToAdminSection('users')} type="button">去管理用户</button>
              </div>
            </section>

            <section className="admin-stack">
              <section className="panel-card">
                <div className="panel-title"><Settings size={16} /> 管理员账号</div>
                <form className="admin-form" onSubmit={onSubmitAdminProfile}>
                  <label>
                    管理员用户名
                    <input autoComplete="username" id="admin-profile-username" name="username" value={adminProfile.username} onChange={(event) => setAdminProfile((prev) => ({ ...prev, username: event.target.value }))} />
                  </label>
                  <label>
                    当前密码
                    <input autoComplete="current-password" id="admin-profile-current-password" name="current_password" type="password" value={adminProfile.current_password} onChange={(event) => setAdminProfile((prev) => ({ ...prev, current_password: event.target.value }))} />
                  </label>
                  <label>
                    新密码
                    <input autoComplete="new-password" id="admin-profile-new-password" name="new_password" type="password" value={adminProfile.new_password} onChange={(event) => setAdminProfile((prev) => ({ ...prev, new_password: event.target.value }))} />
                  </label>
                  {adminProfileMessage ? <div className="success-text">{adminProfileMessage}</div> : null}
                  <button className="primary-btn" type="submit">更新管理员账号</button>
                </form>
              </section>

              <section className="panel-card">
                <div className="panel-title"><UserRound size={16} /> 注册设置</div>
                <div className="settings-stack">
                  <label className="checkbox-row checkbox-card">
                    <input checked={adminSettings.allow_registration} id="admin-overview-allow-registration" name="allow_registration" onChange={(event) => void toggleAllowRegistration(event.target.checked)} type="checkbox" />
                    <span>{adminSettings.allow_registration ? '允许普通用户注册' : '关闭普通用户注册'}</span>
                  </label>
                  {userAdminMessage ? <div className={userAdminError ? 'error-text' : 'success-text'}>{userAdminMessage}</div> : null}
                </div>
              </section>
            </section>
          </section>
        ) : null}

        {adminSection === 'providers' ? (
          <>
            <section className="panel-card admin-section-intro">
              <div>
                <div className="panel-title"><Shield size={16} /> 供应商管理</div>
                <p>单独维护模型接入、能力开关和输出限制。编辑已有供应商时，留空连接 URL 或 Key 会保留当前值。</p>
              </div>
              <div className="meta-chip soft compact">共 {adminProviders.length} 个供应商</div>
            </section>

            <section className="admin-detail-grid">
              <section className="panel-card">
                <div className="panel-title"><Shield size={16} /> {editingProviderId ? '编辑供应商' : '添加供应商'}</div>
                <form className="admin-form" onSubmit={onSubmitProvider}>
                  <label>
                    供应商名称
                    <input autoComplete="off" id="provider-name" name="provider_name" value={providerForm.name} onChange={(event) => setProviderForm((prev) => ({ ...prev, name: event.target.value }))} />
                  </label>
                  <label>
                    接口格式
                    <select
                      id="provider-api-format"
                      name="api_format"
                      value={providerForm.api_format}
                      onChange={(event) => {
                        const apiFormat = event.target.value as ProviderApiFormat
                        setProviderForm((prev) => ({
                          ...prev,
                          api_format: apiFormat,
                          thinking_effort: normalizeThinkingEffort(prev.thinking_effort, apiFormat),
                        }))
                      }}
                    >
                      <option value="anthropic_messages">Anthropic Messages</option>
                      <option value="openai_chat">OpenAI Chat Completions</option>
                      <option value="deepseek_chat">DeepSeek Chat Completions</option>
                      <option value="siliconflow_chat">SiliconFlow Chat Completions</option>
                      <option value="openai_responses">OpenAI Responses</option>
                      <option value="gemini">Gemini</option>
                    </select>
                  </label>
                  {editingProviderId ? (
                    <div className="connection-hint-card">
                      <div>
                        <strong>留空连接信息会保留现有值</strong>
                        <span>仅在需要切换地址或密钥时重新填写，空白不会覆盖当前配置。</span>
                      </div>
                    </div>
                  ) : null}
                  <label>
                    API URL
                    <input
                      autoComplete="url"
                      id="provider-api-url"
                      name="api_url"
                      value={providerForm.api_url}
                      onChange={(event) => setProviderForm((prev) => ({ ...prev, api_url: event.target.value }))}
                      placeholder={providerApiUrlPlaceholder}
                    />
                  </label>
                  <label>
                    API Key
                    <input
                      autoComplete="off"
                      id="provider-api-key"
                      name="api_key"
                      type="password"
                      value={providerForm.api_key}
                      onChange={(event) => setProviderForm((prev) => ({ ...prev, api_key: event.target.value }))}
                      placeholder="输入供应商密钥"
                    />
                  </label>
                  <label>
                    模型名称
                    <input autoComplete="off" id="provider-model-name" name="model_name" value={providerForm.model_name} onChange={(event) => setProviderForm((prev) => ({ ...prev, model_name: event.target.value }))} />
                  </label>
                  <div className="inline-grid">
                    <label>
                      最大上下文
                      <input id="provider-max-context-window" name="max_context_window" type="number" value={providerForm.max_context_window} onChange={(event) => setProviderForm((prev) => ({ ...prev, max_context_window: Number(event.target.value) }))} />
                    </label>
                    <label>
                      最大输出
                      <input id="provider-max-output-tokens" name="max_output_tokens" type="number" value={providerForm.max_output_tokens} onChange={(event) => setProviderForm((prev) => ({ ...prev, max_output_tokens: Number(event.target.value) }))} />
                    </label>
                  </div>
                  <div className="provider-option-group">
                    <div className="provider-option-heading">
                      <span>模型能力</span>
                      <small>这些开关决定聊天页会开放哪些输入和工具能力。</small>
                    </div>
                    <div className="provider-option-grid">
                      {providerCapabilities.map((capability) => (
                        <label className="provider-option-card" key={capability.field}>
                          <input
                            checked={providerForm[capability.field]}
                            id={`provider-${capability.field}`}
                            name={capability.field}
                            onChange={(event) => updateProviderCapability(capability.field, event.target.checked)}
                            type="checkbox"
                          />
                          <span>{capability.checkboxLabel}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="provider-option-group">
                    <div className="provider-option-heading">
                      <span>供应商状态</span>
                      <small>关闭后普通用户不能再选择该供应商，已有会话记录不会被删除。</small>
                    </div>
                    <label className="provider-option-card provider-status-option">
                      <input checked={providerForm.is_enabled} id="provider-is-enabled" name="is_enabled" onChange={(event) => setProviderForm((prev) => ({ ...prev, is_enabled: event.target.checked }))} type="checkbox" />
                      <span>启用供应商</span>
                    </label>
                  </div>
                  <label>
                    思考努力等级
                    <select
                      id="provider-thinking-effort"
                      name="thinking_effort"
                      value={providerForm.thinking_effort}
                      onChange={(event) => setProviderForm((prev) => ({ ...prev, thinking_effort: event.target.value as ThinkingEffort }))}
                    >
                      {thinkingEffortOptions.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </label>
                  {providerError ? <div className="error-text">{providerError}</div> : null}
                  {providerSuccess ? <div className="success-text">{providerSuccess}</div> : null}
                  <div className="action-row">
                    <button className="primary-btn" type="submit">{editingProviderId ? '保存修改' : '添加供应商'}</button>
                    {editingProviderId ? (
                      <button className="ghost-btn" onClick={cancelEditingProvider} type="button">
                        取消编辑
                      </button>
                    ) : null}
                  </div>
                </form>
              </section>

              <section className="panel-card provider-table-card">
                <div className="panel-title"><LayoutDashboard size={16} /> 已配置供应商</div>
                <div className="provider-table">
                  {adminProviders.map((provider) => (
                    <div className="provider-row" key={provider.id}>
                      <div>
                        <strong>{provider.name}</strong>
                        <span>{provider.model_name}</span>
                      </div>
                      <div className="provider-flags">
                        <span className="meta-chip">{providerApiFormatLabels[provider.api_format]}</span>
                        {providerCapabilities.map((capability) =>
                          provider[capability.field] ? <span className="meta-chip" key={capability.field}>{capability.chipLabel}</span> : null,
                        )}
                        <span className="meta-chip">输出 {provider.max_output_tokens}</span>
                        <span className="meta-chip">{provider.is_enabled ? '启用中' : '已禁用'}</span>
                      </div>
                      <div className="provider-actions">
                        <span className="masked-key">{provider.api_key_masked}</span>
                        <button className="ghost-btn" onClick={() => void editProvider(provider)} type="button">编辑</button>
                        <button className="ghost-btn danger-text" onClick={() => void removeProvider(provider)} type="button">删除</button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </section>
          </>
        ) : null}

        {adminSection === 'search-mcp' ? (
          <>
            <section className="panel-card admin-section-intro">
              <div>
                <div className="panel-title"><Search size={16} /> 搜索 MCP 管理</div>
                <p>集中配置聊天页可选的搜索 MCP。Exa 的 API Key 可选，Tavily 必须配置 Key 才能真正可用。</p>
              </div>
              <div className="meta-chip soft compact">搜索源 {adminSearchProviders ? Object.keys(adminSearchProviders).length : 0} 个</div>
            </section>

            {searchProviderMessage ? (
              <section className="panel-card">
                <div className={searchProviderError ? 'error-text' : 'success-text'}>{searchProviderMessage}</div>
              </section>
            ) : null}

            <section className="search-mcp-grid">
              <section className="panel-card search-mcp-card">
                <div className="panel-title"><Shield size={16} /> Exa 搜索</div>
                <p className="search-mcp-description">
                  可直接启用给用户使用。API Key 不是必填项；填写后会以 `x-api-key` 发送给 Exa，用于更高额度或生产环境。
                </p>
                <div className="connection-hint-card compact">
                  <div>
                    <strong>当前状态：{adminSearchProviders?.exa?.is_enabled ? '已启用' : '已停用'}</strong>
                    <span className="hint-text">已保存 Key：{adminSearchProviders?.exa?.api_key_masked ?? '未知'}</span>
                  </div>
                </div>
                <form className="admin-form" onSubmit={(event) => onSubmitSearchProvider('exa', event)}>
                  <label className="search-toggle-card">
                    <div className="search-toggle-copy">
                      <strong>允许用户在聊天中选择 Exa 搜索</strong>
                      <span>关闭后，聊天页不会再显示 Exa 作为可选搜索来源。</span>
                    </div>
                    <input
                      checked={searchProviderForms.exa.is_enabled}
                      id="search-mcp-exa-enabled"
                      name="exa_enabled"
                      onChange={(event) => updateSearchProviderForm('exa', { is_enabled: event.target.checked })}
                      type="checkbox"
                    />
                  </label>
                  <label>
                    Exa API Key（可选）
                    <input
                      autoComplete="off"
                      id="search-mcp-exa-api-key"
                      name="exa_api_key"
                      type="password"
                      value={searchProviderForms.exa.api_key}
                      onChange={(event) => updateSearchProviderForm('exa', { api_key: event.target.value })}
                      placeholder="留空会保留当前已保存的 Key"
                    />
                  </label>
                  <button className="primary-btn" type="submit">保存 Exa 配置</button>
                </form>
              </section>

              <section className="panel-card search-mcp-card">
                <div className="panel-title"><Shield size={16} /> Tavily 搜索</div>
                <p className="search-mcp-description">
                  Tavily 需要先配置 API Key 才能正常联网搜索。即使勾选启用，没有 Key 时聊天页也会显示为不可用。
                </p>
                <div className="connection-hint-card compact">
                  <div>
                    <strong>
                      当前状态：
                      {adminSearchProviders?.tavily?.is_enabled ? (adminSearchProviders?.tavily?.is_configured ? '已启用' : '已启用但未配置完成') : '已停用'}
                    </strong>
                    <span className="hint-text">已保存 Key：{adminSearchProviders?.tavily?.api_key_masked ?? '未知'}</span>
                  </div>
                </div>
                <form className="admin-form" onSubmit={(event) => onSubmitSearchProvider('tavily', event)}>
                  <label className="search-toggle-card">
                    <div className="search-toggle-copy">
                      <strong>允许用户在聊天中选择 Tavily 搜索</strong>
                      <span>关闭后，聊天页不会再显示 Tavily 作为可选搜索来源。</span>
                    </div>
                    <input
                      checked={searchProviderForms.tavily.is_enabled}
                      id="search-mcp-tavily-enabled"
                      name="tavily_enabled"
                      onChange={(event) => updateSearchProviderForm('tavily', { is_enabled: event.target.checked })}
                      type="checkbox"
                    />
                  </label>
                  <label>
                    Tavily API Key（必填）
                    <input
                      autoComplete="off"
                      id="search-mcp-tavily-api-key"
                      name="tavily_api_key"
                      type="password"
                      value={searchProviderForms.tavily.api_key}
                      onChange={(event) => updateSearchProviderForm('tavily', { api_key: event.target.value })}
                      placeholder="输入 Tavily API Key，留空会保留当前已保存的 Key"
                    />
                  </label>
                  <button className="primary-btn" type="submit">保存 Tavily 配置</button>
                </form>
              </section>
            </section>
          </>
        ) : null}

        {adminSection === 'users' ? (
          <>
            <section className="panel-card admin-section-intro">
              <div>
                <div className="panel-title"><UserRound size={16} /> 用户管理</div>
                <p>把注册开关、手动创建、启用状态和密码重置集中到用户子页，降低后台操作噪音。</p>
              </div>
              <div className="meta-chip soft compact">共 {adminUsers.length} 个用户</div>
            </section>

            <section className="admin-detail-grid">
              <section className="panel-card">
                <div className="panel-title"><UserRound size={16} /> 注册与创建</div>
                <div className="settings-stack">
                  <label className="checkbox-row checkbox-card">
                    <input checked={adminSettings.allow_registration} id="admin-users-allow-registration" name="allow_registration" onChange={(event) => void toggleAllowRegistration(event.target.checked)} type="checkbox" />
                    <span>{adminSettings.allow_registration ? '允许普通用户注册' : '关闭普通用户注册'}</span>
                  </label>
                  <form className="admin-form" onSubmit={onSubmitAdminUser}>
                    <div className="inline-grid">
                      <label>
                        用户名
                        <input autoComplete="username" id="admin-user-username" name="username" value={userForm.username} onChange={(event) => setUserForm((prev) => ({ ...prev, username: event.target.value }))} />
                      </label>
                      <label>
                        初始密码
                        <input autoComplete="new-password" id="admin-user-password" name="password" type="password" value={userForm.password} onChange={(event) => setUserForm((prev) => ({ ...prev, password: event.target.value }))} />
                      </label>
                    </div>
                    <div className="inline-grid">
                      <label>
                        角色
                        <select id="admin-user-role" name="role" value={userForm.role} onChange={(event) => setUserForm((prev) => ({ ...prev, role: event.target.value as 'admin' | 'user' }))}>
                          <option value="user">普通用户</option>
                          <option value="admin">管理员</option>
                        </select>
                      </label>
                      <label className="checkbox-row checkbox-row-inline">
                        <input checked={userForm.is_enabled} id="admin-user-is-enabled" name="is_enabled" onChange={(event) => setUserForm((prev) => ({ ...prev, is_enabled: event.target.checked }))} type="checkbox" />
                        创建后立即启用
                      </label>
                    </div>
                    {userAdminMessage ? <div className={userAdminError ? 'error-text' : 'success-text'}>{userAdminMessage}</div> : null}
                    <button className="primary-btn" type="submit">手动添加用户</button>
                  </form>
                </div>
              </section>

              <section className="panel-card provider-table-card">
                <div className="panel-title"><LayoutDashboard size={16} /> 用户列表</div>
                <div className="user-search-bar">
                  <input autoComplete="off" id="admin-user-search" name="user_search" placeholder="搜索用户名" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} />
                </div>
                <div className="provider-table">
                  {filteredAdminUsers.map((managedUser) => (
                    <div className="provider-row user-row" key={managedUser.id}>
                      <div>
                        <strong>{managedUser.username}</strong>
                        <span>{managedUser.role === 'admin' ? '管理员' : '普通用户'}</span>
                      </div>
                      <div className="provider-flags">
                        <span className="meta-chip">{managedUser.is_enabled ? '启用中' : '已停用'}</span>
                        <span className="meta-chip">创建于 {formatDateTime(managedUser.created_at)}</span>
                      </div>
                      <div className="provider-actions">
                        <button className="ghost-btn" onClick={() => void resetAdminUserPassword(managedUser)} type="button">重置密码</button>
                        <button className="ghost-btn" onClick={() => void toggleUserEnabled(managedUser)} type="button">
                          {managedUser.is_enabled ? '停用' : '启用'}
                        </button>
                        <button className="ghost-btn danger-text" onClick={() => void removeAdminUser(managedUser)} type="button">删除</button>
                      </div>
                    </div>
                  ))}
                  {filteredAdminUsers.length === 0 ? <div className="empty-tip">没有匹配的用户。</div> : null}
                </div>
              </section>
            </section>
          </>
        ) : null}
      </main>
    </div>
  )
}
