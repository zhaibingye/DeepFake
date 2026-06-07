import { Bot, LayoutDashboard, LogOut, Pencil, Plus, Search, Settings, Shield, Sparkles, Trash2, UserRound } from 'lucide-react'

import type { ProviderApiFormat, ThinkingEffort } from '../../types'
import type {
  AdminManagedUser,
  AdminProviderGroup,
  AdminSettings,
  SearchProviderAvailability,
  SearchProviderKind,
} from '../../types'
import { createDefaultProviderModel, type ProviderFormState } from './providerForm'
import type { SearchProviderFormState } from './controller'
import { normalizeThinkingEffort } from '../../appState'
import { formatDateTime } from '../../utils'

export type AdminSection = 'overview' | 'providers' | 'search-mcp' | 'users'

type ProviderCapabilityField = keyof Pick<
  ProviderFormState['models'][number],
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
  adminProviders: AdminProviderGroup[]
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
  editProvider: (provider: AdminProviderGroup) => void
  removeProvider: (provider: AdminProviderGroup) => void
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
  const enabledProvidersCount = adminProviders.filter((provider) => provider.models.some((model) => model.is_enabled)).length
  const providerModelCount = adminProviders.reduce((total, provider) => total + provider.models.length, 0)
  const enabledProviderModelCount = adminProviders.reduce(
    (total, provider) => total + provider.models.filter((model) => model.is_enabled).length,
    0,
  )

  const updateProviderModel = (
    modelIndex: number,
    patch: Partial<ProviderFormState['models'][number]>,
  ) => {
    setProviderForm((prev) => ({
      ...prev,
      models: prev.models.map((model, index) => (index === modelIndex ? { ...model, ...patch } : model)),
    }))
  }

  const updateProviderCapability = (modelIndex: number, field: ProviderCapabilityField, checked: boolean) => {
    updateProviderModel(modelIndex, { [field]: checked })
  }

  const addProviderModel = () => {
    setProviderForm((prev) => {
      const thinking_effort = normalizeThinkingEffort('high', prev.api_format)
      return {
        ...prev,
        models: [...prev.models, { ...createDefaultProviderModel(), thinking_effort }],
      }
    })
  }

  const removeProviderModel = (modelIndex: number) => {
    setProviderForm((prev) => {
      if (prev.models.length <= 1) return prev
      return {
        ...prev,
        models: prev.models.filter((_, index) => index !== modelIndex),
      }
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
                  <small>{enabledProvidersCount} 个含启用模型</small>
                </div>
                <div className="admin-metric-card">
                  <strong>{providerModelCount}</strong>
                  <span>模型总数</span>
                  <small>{enabledProviderModelCount} 个启用中</small>
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
                  <label className="provider-option-card">
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
                <p>供应商只维护共享连接信息；同一供应商下可以配置多个模型，每个模型单独维护能力开关和输出限制。</p>
              </div>
              <div className="meta-chip soft compact">共 {adminProviders.length} 个供应商 / {providerModelCount} 个模型</div>
            </section>

            <section className="admin-detail-grid">
              <section className="panel-card">
                <div className="panel-title"><Shield size={16} /> {editingProviderId ? '编辑供应商' : '添加供应商'}</div>
                <form className="admin-form" onSubmit={onSubmitProvider}>
                  <section className="provider-config-section provider-connection-section">
                    <div className="provider-option-heading">
                      <span>共享连接配置</span>
                      <small>同一供应商下所有模型共用接口格式、URL 和 Key。</small>
                    </div>
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
                            models: prev.models.map((model) => ({
                              ...model,
                              thinking_effort: normalizeThinkingEffort(model.thinking_effort, apiFormat),
                            })),
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
                  </section>
                  <section className="provider-config-section provider-models-editor">
                    <div className="provider-option-heading provider-models-heading">
                      <div>
                        <span>模型配置</span>
                        <small>URL 和 Key 由供应商共享，下面每个模型的能力、上下文、输出和状态互不影响。</small>
                      </div>
                      <button className="provider-add-model-btn" onClick={addProviderModel} type="button">
                        <Plus size={15} />
                        添加模型
                      </button>
                    </div>
                    {providerForm.models.map((model, modelIndex) => (
                      <section className="provider-model-editor" key={model.id ?? `new-${modelIndex}`}>
                        <div className="provider-model-editor-head">
                          <strong>模型 {modelIndex + 1}</strong>
                          <button
                            className="mini-icon-btn danger"
                            disabled={providerForm.models.length <= 1}
                            onClick={() => removeProviderModel(modelIndex)}
                            title="移除模型"
                            type="button"
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                        <label>
                          模型名称
                          <input
                            autoComplete="off"
                            id={`provider-model-name-${modelIndex}`}
                            name={`model_name_${modelIndex}`}
                            value={model.model_name}
                            onChange={(event) => updateProviderModel(modelIndex, { model_name: event.target.value })}
                          />
                        </label>
                        <div className="inline-grid">
                          <label>
                            最大上下文
                            <input
                              id={`provider-max-context-window-${modelIndex}`}
                              name={`max_context_window_${modelIndex}`}
                              type="number"
                              value={model.max_context_window}
                              onChange={(event) => updateProviderModel(modelIndex, { max_context_window: Number(event.target.value) })}
                            />
                          </label>
                          <label>
                            最大输出
                            <input
                              id={`provider-max-output-tokens-${modelIndex}`}
                              name={`max_output_tokens_${modelIndex}`}
                              type="number"
                              value={model.max_output_tokens}
                              onChange={(event) => updateProviderModel(modelIndex, { max_output_tokens: Number(event.target.value) })}
                            />
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
                                  checked={model[capability.field]}
                                  id={`provider-${capability.field}-${modelIndex}`}
                                  name={`${capability.field}_${modelIndex}`}
                                  onChange={(event) => updateProviderCapability(modelIndex, capability.field, event.target.checked)}
                                  type="checkbox"
                                />
                                <span>{capability.checkboxLabel}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                        <div className="inline-grid">
                          <label>
                            思考努力等级
                            <select
                              id={`provider-thinking-effort-${modelIndex}`}
                              name={`thinking_effort_${modelIndex}`}
                              value={model.thinking_effort}
                              onChange={(event) => updateProviderModel(modelIndex, { thinking_effort: event.target.value as ThinkingEffort })}
                            >
                              {thinkingEffortOptions.map((option) => (
                                <option key={option} value={option}>{option}</option>
                              ))}
                            </select>
                          </label>
                          <label className="provider-option-card provider-status-option">
                            <input
                              checked={model.is_enabled}
                              id={`provider-is-enabled-${modelIndex}`}
                              name={`is_enabled_${modelIndex}`}
                              onChange={(event) => updateProviderModel(modelIndex, { is_enabled: event.target.checked })}
                              type="checkbox"
                            />
                            <span>{model.is_enabled ? '模型已启用' : '模型已停用'}</span>
                          </label>
                        </div>
                      </section>
                    ))}
                  </section>
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
                    <section className="provider-group-row" key={provider.id}>
                      <div className="provider-group-head">
                        <div>
                          <strong>{provider.name}</strong>
                          <span>{providerApiFormatLabels[provider.api_format]} / {provider.models.length} 个模型</span>
                          <span className="masked-key">{provider.api_key_masked}</span>
                        </div>
                        <div className="provider-actions">
                          <button className="ghost-btn" onClick={() => void editProvider(provider)} type="button">
                            <Pencil size={15} />
                            编辑
                          </button>
                          <button className="ghost-btn danger-text" onClick={() => void removeProvider(provider)} type="button">
                            <Trash2 size={15} />
                            删除
                          </button>
                        </div>
                      </div>
                      <div className="provider-model-list">
                        {provider.models.map((model) => (
                          <div className="provider-row provider-model-row" key={model.id}>
                            <div>
                              <strong>{model.model_name}</strong>
                              <span>{model.is_enabled ? '启用中' : '已禁用'}</span>
                            </div>
                            <div className="provider-flags">
                              {providerCapabilities.map((capability) =>
                                model[capability.field] ? <span className="meta-chip" key={capability.field}>{capability.chipLabel}</span> : null,
                              )}
                              <span className="meta-chip">上下文 {model.max_context_window}</span>
                              <span className="meta-chip">输出 {model.max_output_tokens}</span>
                              <span className="meta-chip">思考 {model.thinking_effort}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </section>
                  ))}
                  {adminProviders.length === 0 ? <div className="empty-tip">暂无供应商。</div> : null}
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
                  <div className="search-toggle-card">
                    <div className="search-toggle-copy">
                      <strong>允许用户在聊天中选择 Exa 搜索</strong>
                      <span>关闭后，聊天页不会再显示 Exa 作为可选搜索来源。</span>
                    </div>
                    <label className="provider-option-card">
                      <input
                        checked={searchProviderForms.exa.is_enabled}
                        id="search-mcp-exa-enabled"
                        name="exa_enabled"
                        onChange={(event) => updateSearchProviderForm('exa', { is_enabled: event.target.checked })}
                        type="checkbox"
                      />
                      <span>{searchProviderForms.exa.is_enabled ? '已启用' : '已停用'}</span>
                    </label>
                  </div>
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
                  <div className="search-toggle-card">
                    <div className="search-toggle-copy">
                      <strong>允许用户在聊天中选择 Tavily 搜索</strong>
                      <span>关闭后，聊天页不会再显示 Tavily 作为可选搜索来源。</span>
                    </div>
                    <label className="provider-option-card">
                      <input
                        checked={searchProviderForms.tavily.is_enabled}
                        id="search-mcp-tavily-enabled"
                        name="tavily_enabled"
                        onChange={(event) => updateSearchProviderForm('tavily', { is_enabled: event.target.checked })}
                        type="checkbox"
                      />
                      <span>{searchProviderForms.tavily.is_enabled ? '已启用' : '已停用'}</span>
                    </label>
                  </div>
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
                  <label className="provider-option-card">
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
                      <label className="provider-option-card">
                        <input checked={userForm.is_enabled} id="admin-user-is-enabled" name="is_enabled" onChange={(event) => setUserForm((prev) => ({ ...prev, is_enabled: event.target.checked }))} type="checkbox" />
                        <span>{userForm.is_enabled ? '创建后立即启用' : '创建后暂不启用'}</span>
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
