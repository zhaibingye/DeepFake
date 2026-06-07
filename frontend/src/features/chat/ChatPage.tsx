import { ArrowUp, Bot, BrainCircuit, Check, ChevronDown, FileImage, LayoutDashboard, LogOut, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Pencil, Sparkles, Square, Trash2, UserRound, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { MarkdownView } from '../../components/MarkdownView'
import { TimelineList } from '../../components/chat/TimelineList'
import { toRenderableTimeline } from '../../components/chat/timeline'
import { DeepfakeWhaleIcon } from '../common/DeepfakeWhaleIcon'
import {
  isSearchProviderAvailable,
  searchProviderLabel,
  searchProviderOptions,
} from './searchProviders'
import type {
  Attachment,
  ChatDonePayload,
  Conversation,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
  ThinkingEffort,
  User,
} from '../../types'
import { formatDateTime, messageImages, messagePlainText } from '../../utils'

type TimelineViewState = {
  parts: ReturnType<typeof toRenderableTimeline>
  revision: string
  expandedById: Record<string, boolean>
  setExpanded: (id: string, nextExpanded: boolean) => void
}

type PendingUserMessage = {
  text: string
  attachments: Attachment[]
  createdAt: string
}

type ToolDrawer = 'thinking' | 'search' | 'provider'

type ProviderGroup = {
  id: string
  name: string
  apiFormat: Provider['api_format']
  models: Provider[]
}

type ChatPageProps = {
  sidebarCollapsed: boolean
  chatLoading: boolean
  conversations: Conversation[]
  activeConversationId: number | null
  currentConversation: Conversation | null
  currentConversationProvider: Provider | null
  selectedProvider: Provider | null
  selectedProviderId: number | null
  providers: Provider[]
  user: User
  hasVisibleConversation: boolean
  messages: ChatDonePayload['messages']
  pendingUserMessage: PendingUserMessage | null
  streamingTimeline: TimelineViewState
  messageEndRef: React.RefObject<HTMLDivElement | null>
  fileInputRef: React.RefObject<HTMLInputElement | null>
  input: string
  attachments: Attachment[]
  enableThinking: boolean
  enableSearch: boolean
  searchProvider: SearchProviderKind
  searchProviders: SearchProviderAvailability | null
  effort: ThinkingEffort
  thinkingEffortOptions: ThinkingEffort[]
  chatError: string
  selectedProviderSupportsToolCalling: boolean
  toggleSidebar: () => void
  startNewConversation: () => void
  openConversation: (conversationId: number) => void
  renameConversation: (conversation: Conversation) => void
  removeConversation: (conversation: Conversation) => void
  navigateToAdmin: () => void
  handleLogout: () => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
  setInput: (value: string) => void
  handleComposerKeyDown: (event: React.KeyboardEvent<HTMLTextAreaElement>) => void
  removeAttachment: (name: string) => void
  setEnableThinking: React.Dispatch<React.SetStateAction<boolean>>
  setEnableSearch: React.Dispatch<React.SetStateAction<boolean>>
  setChatError: (value: string) => void
  setSearchProvider: (value: SearchProviderKind) => void
  applyProviderSelection: (nextProviderId: number | null) => void
  triggerFileSelect: () => void
  stopStreaming: () => void
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void
  setEffort: (value: ThinkingEffort) => void
}

function renderImageGrid(images: Array<Pick<Attachment, 'media_type' | 'data'>>, keyPrefix: string) {
  if (!images.length) {
    return null
  }

  return (
    <div className="image-grid">
      {images.map((image, index) => (
        <img key={`${keyPrefix}-${index}`} alt="uploaded" src={`data:${image.media_type};base64,${image.data}`} />
      ))}
    </div>
  )
}

function thinkingEffortLabel(value: ThinkingEffort) {
  const labels: Record<ThinkingEffort, string> = {
    low: '低',
    medium: '中',
    high: '高',
    max: '最高',
    xhigh: '超高',
  }
  return labels[value]
}

function providerApiFormatLabel(value: Provider['api_format']) {
  const labels: Record<Provider['api_format'], string> = {
    anthropic_messages: 'Anthropic Messages',
    openai_chat: 'OpenAI Chat',
    deepseek_chat: 'DeepSeek Chat',
    siliconflow_chat: 'SiliconFlow Chat',
    openai_responses: 'OpenAI Responses',
    gemini: 'Gemini',
  }
  return labels[value]
}

function modelCapabilityText(provider: Provider) {
  const capabilities = [
    provider.supports_thinking ? '思考' : null,
    provider.supports_vision ? '视觉' : null,
    provider.supports_tool_calling ? '工具调用' : null,
  ].filter(Boolean)

  return capabilities.length ? capabilities.join(' · ') : '基础对话'
}

function groupProviders(providers: Provider[]) {
  const groups: ProviderGroup[] = []
  const groupById = new Map<string, ProviderGroup>()

  providers.forEach((provider) => {
    const id = String(provider.connection_id ?? provider.id)
    const existingGroup = groupById.get(id)
    if (existingGroup) {
      existingGroup.models.push(provider)
      return
    }

    const group = {
      id,
      name: provider.name,
      apiFormat: provider.api_format,
      models: [provider],
    }
    groupById.set(id, group)
    groups.push(group)
  })

  return groups
}

export function ChatPage({
  sidebarCollapsed,
  chatLoading,
  conversations,
  activeConversationId,
  currentConversation,
  currentConversationProvider,
  selectedProvider,
  selectedProviderId,
  providers,
  user,
  hasVisibleConversation,
  messages,
  pendingUserMessage,
  streamingTimeline,
  messageEndRef,
  fileInputRef,
  input,
  attachments,
  enableThinking,
  enableSearch,
  searchProvider,
  searchProviders,
  effort,
  thinkingEffortOptions,
  chatError,
  selectedProviderSupportsToolCalling,
  toggleSidebar,
  startNewConversation,
  openConversation,
  renameConversation,
  removeConversation,
  navigateToAdmin,
  handleLogout,
  onSubmit,
  setInput,
  handleComposerKeyDown,
  removeAttachment,
  setEnableThinking,
  setEnableSearch,
  setChatError,
  setSearchProvider,
  applyProviderSelection,
  triggerFileSelect,
  stopStreaming,
  handleFileChange,
  setEffort,
}: ChatPageProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [openToolDrawer, setOpenToolDrawer] = useState<ToolDrawer | null>(null)
  const toolDrawerRef = useRef<HTMLDivElement | null>(null)
  const visibleToolDrawer = (
    openToolDrawer === 'thinking' && !selectedProvider?.supports_thinking
      ? null
      : openToolDrawer === 'search' && !selectedProviderSupportsToolCalling
        ? null
        : openToolDrawer
  )

  const closeMobileSidebar = useCallback(() => setMobileSidebarOpen(false), [])

  const toggleToolDrawer = useCallback((drawer: ToolDrawer) => {
    setOpenToolDrawer((current) => (current === drawer ? null : drawer))
  }, [])

  const wrappedStartNewConversation = useCallback(() => {
    closeMobileSidebar()
    setOpenToolDrawer(null)
    startNewConversation()
  }, [closeMobileSidebar, startNewConversation])

  const wrappedOpenConversation = useCallback((conversationId: number) => {
    closeMobileSidebar()
    setOpenToolDrawer(null)
    void openConversation(conversationId)
  }, [closeMobileSidebar, openConversation])

  const wrappedNavigateToAdmin = useCallback(() => {
    closeMobileSidebar()
    setOpenToolDrawer(null)
    navigateToAdmin()
  }, [closeMobileSidebar, navigateToAdmin])

  const wrappedHandleLogout = useCallback(() => {
    closeMobileSidebar()
    setOpenToolDrawer(null)
    handleLogout()
  }, [closeMobileSidebar, handleLogout])

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > 860) {
        setMobileSidebarOpen(false)
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    if (!mobileSidebarOpen) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMobileSidebarOpen(false)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [mobileSidebarOpen])

  useEffect(() => {
    if (!visibleToolDrawer) return
    const handlePointerDown = (event: PointerEvent) => {
      if (toolDrawerRef.current?.contains(event.target as Node)) {
        return
      }
      setOpenToolDrawer(null)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenToolDrawer(null)
      }
    }
    document.addEventListener('pointerdown', handlePointerDown)
    window.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      window.removeEventListener('keydown', handleKey)
    }
  }, [visibleToolDrawer])

  const toolButtonClass = (drawer: ToolDrawer, active = false) => (
    ['tool-btn', active ? 'active' : '', visibleToolDrawer === drawer ? 'open' : ''].filter(Boolean).join(' ')
  )

  const selectedProviderLabel = selectedProvider?.model_name ?? '未选择'
  const selectedProviderTitle = selectedProvider ? `${selectedProvider.name} / ${selectedProvider.model_name}` : '未选择'
  const selectedSearchProviderLabel = searchProviderLabel(searchProvider)
  const providerGroups = useMemo(() => groupProviders(providers), [providers])
  const canSendMessage = Boolean(selectedProviderId && (input.trim().length > 0 || attachments.length > 0))

  return (
    <div className={sidebarCollapsed ? 'chat-shell sidebar-collapsed' : 'chat-shell'}>
      <div className="mobile-topbar">
        <button
          aria-label="展开侧边栏"
          className="icon-btn sidebar-toggle"
          onClick={() => setMobileSidebarOpen(true)}
          title="展开侧边栏"
          type="button"
        >
          <PanelLeftOpen size={18} />
        </button>
        <div className="mobile-topbar-title">
          {currentConversation?.title ?? 'deepfake'}
        </div>
        <button
          aria-label="开启新对话"
          className="icon-btn"
          onClick={wrappedStartNewConversation}
          title="开启新对话"
          type="button"
        >
          <MessageSquarePlus size={18} />
        </button>
      </div>

      {mobileSidebarOpen ? (
        <div
          className="mobile-sidebar-overlay"
          onClick={closeMobileSidebar}
          role="presentation"
        />
      ) : null}

      <aside className={(sidebarCollapsed && !mobileSidebarOpen ? 'chat-sidebar collapsed' : 'chat-sidebar') + (mobileSidebarOpen ? ' mobile-open' : '')}>
        <div className="sidebar-top">
          <div className="sidebar-brand">
            <div className="brand-lockup">
              {sidebarCollapsed && !mobileSidebarOpen ? (
                <div className="brand-mark solid"><DeepfakeWhaleIcon className="whale-icon" /></div>
              ) : (
                <img alt="deepfake" className="brand-logo-image" src="/deepfake-logo.png" />
              )}
            </div>
            <button aria-label={mobileSidebarOpen ? '关闭侧边栏' : (sidebarCollapsed ? '展开侧边栏' : '收起侧边栏')} className="icon-btn sidebar-toggle" onClick={mobileSidebarOpen ? closeMobileSidebar : toggleSidebar} title={mobileSidebarOpen ? '关闭侧边栏' : (sidebarCollapsed ? '展开侧边栏' : '收起侧边栏')} type="button">
              {mobileSidebarOpen ? <X size={16} /> : (sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />)}
            </button>
          </div>

          <button
            className={sidebarCollapsed && !mobileSidebarOpen ? 'new-chat-btn icon-only' : 'new-chat-btn'}
            disabled={chatLoading}
            onClick={wrappedStartNewConversation}
            title="开启新对话"
            type="button"
          >
            <MessageSquarePlus size={16} />
            {sidebarCollapsed && !mobileSidebarOpen ? null : '开启新对话'}
          </button>
        </div>

        <div className={sidebarCollapsed && !mobileSidebarOpen ? 'conversation-list collapsed' : 'conversation-list'}>
          {sidebarCollapsed && !mobileSidebarOpen ? null : <div className="section-title">7 天内</div>}
          {!(sidebarCollapsed && !mobileSidebarOpen) && conversations.length === 0 ? <div className="empty-tip">还没有会话，发一条消息开始。</div> : null}
          {conversations.map((conversation) => (
            <div key={conversation.id} className={activeConversationId === conversation.id ? 'conversation-item active' : 'conversation-item'}>
              <button
                className="conversation-main"
                disabled={chatLoading}
                onClick={() => wrappedOpenConversation(conversation.id)}
                type="button"
              >
                <span>{sidebarCollapsed && !mobileSidebarOpen ? conversation.title.slice(0, 1) : conversation.title}</span>
                {sidebarCollapsed && !mobileSidebarOpen ? null : <small>{conversation.provider_name} / {conversation.model_name}</small>}
              </button>
              <div className={sidebarCollapsed && !mobileSidebarOpen ? 'conversation-actions hidden' : 'conversation-actions'}>
                <button
                  aria-label="重命名会话"
                  className="mini-icon-btn"
                  disabled={chatLoading}
                  onClick={() => void renameConversation(conversation)}
                  title="重命名会话"
                  type="button"
                >
                  <Pencil size={14} />
                </button>
                <button
                  aria-label="删除会话"
                  className="mini-icon-btn danger"
                  disabled={chatLoading}
                  onClick={() => void removeConversation(conversation)}
                  title="删除会话"
                  type="button"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className={sidebarCollapsed && !mobileSidebarOpen ? 'user-card compact collapsed' : 'user-card compact'}>
            <div className="user-meta">
              <div className="avatar"><UserRound size={15} /></div>
              <div className={sidebarCollapsed && !mobileSidebarOpen ? 'hidden' : ''}>
                <strong>{user.username}</strong>
                <span>{user.role === 'admin' ? '管理员' : '普通用户'}</span>
              </div>
            </div>
            <div className="user-actions">
              {user.role === 'admin' ? (
                <button className="icon-btn" onClick={wrappedNavigateToAdmin} title="管理后台" type="button">
                  <LayoutDashboard size={16} />
                </button>
              ) : null}
              <button className="icon-btn" onClick={wrappedHandleLogout} title="退出登录" type="button">
                <LogOut size={16} />
              </button>
            </div>
          </div>
        </div>
      </aside>

      <main className={hasVisibleConversation ? 'chat-stage' : 'chat-stage empty'}>
        <div className="chat-content">
          <header className={hasVisibleConversation ? 'chat-heading' : 'chat-heading empty'}>
            {!hasVisibleConversation ? (
              <>
                <div className="hero-badge"><DeepfakeWhaleIcon className="whale-icon" /></div>
                <h2>今天有什么可以帮到你？</h2>
              </>
            ) : (
              <>
                <h2>{currentConversation?.title ?? '新对话'}</h2>
                <p>{currentConversationProvider?.name ?? selectedProvider?.name ?? 'AI'} / {currentConversation?.model_name ?? selectedProvider?.model_name ?? ''}</p>
              </>
            )}
          </header>

          {hasVisibleConversation ? (
            <div className="message-stream">
              {messages.map((message) => (
                <article key={message.id} className={message.role === 'user' ? 'message-row user' : 'message-row assistant'}>
                  <div className="message-meta-row">
                    <span className="message-role">{message.role === 'user' ? user.username : currentConversationProvider?.name ?? selectedProvider?.name ?? 'AI'}</span>
                    <time>{formatDateTime(message.created_at)}</time>
                  </div>
                  {message.role === 'assistant' ? (
                    <TimelineList parts={toRenderableTimeline(message)} />
                  ) : (
                    <div className="message-bubble user">
                      <div className="markdown-body">
                        <MarkdownView content={messagePlainText(message.content)} />
                      </div>
                      {renderImageGrid(messageImages(message.content), String(message.id))}
                    </div>
                  )}
                </article>
              ))}
              {pendingUserMessage ? (
                <article className="message-row user pending">
                  <div className="message-meta-row">
                    <span className="message-role">{user.username}</span>
                    <time>{formatDateTime(pendingUserMessage.createdAt)}</time>
                  </div>
                  <div className="message-bubble user">
                    <div className="markdown-body">
                      <MarkdownView content={pendingUserMessage.text || '[图片消息]'} />
                    </div>
                    {renderImageGrid(pendingUserMessage.attachments, 'pending')}
                  </div>
                </article>
              ) : null}
              {streamingTimeline.parts.length ? (
                <article className="message-row assistant">
                  <div className="message-meta-row">
                    <span className="message-role">{selectedProvider?.name ?? 'AI'}</span>
                    <time>{selectedProvider?.model_name ?? ''}</time>
                  </div>
                  <TimelineList
                    parts={streamingTimeline.parts}
                    expandedById={streamingTimeline.expandedById}
                    onToggle={streamingTimeline.setExpanded}
                  />
                </article>
              ) : null}
              <div ref={messageEndRef} />
            </div>
          ) : null}

          <form className={hasVisibleConversation ? 'composer docked compact deepseekish' : 'composer docked center compact deepseekish'} onSubmit={onSubmit}>
            <div className="composer-input-shell">
              <textarea
                className={chatLoading ? 'composer-textarea busy' : 'composer-textarea'}
                id="chat-composer-message"
                name="message"
                placeholder={chatLoading ? '' : (selectedProvider ? `给 ${selectedProvider.name} 发送消息` : '请先让管理员添加供应商')}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                rows={messages.length === 0 ? 3 : 2}
              />
              {chatLoading ? <div className="loading-text in-composer">{enableThinking ? '正在思考并回答...' : '正在回答...'}</div> : null}
            </div>

            {attachments.length ? (
              <div className="attachment-strip">
                {attachments.map((attachment) => (
                  <div className="attachment-item" key={attachment.name}>
                    <FileImage size={14} />
                    <span>{attachment.name}</span>
                    <button className="attachment-remove" onClick={() => removeAttachment(attachment.name)} type="button">
                      x
                    </button>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="composer-toolbar" ref={toolDrawerRef}>
              <div className="left-tools">
                {selectedProvider?.supports_thinking ? (
                  <button
                    aria-controls="chat-tool-drawer"
                    aria-expanded={visibleToolDrawer === 'thinking'}
                    className={toolButtonClass('thinking', enableThinking)}
                    onClick={() => toggleToolDrawer('thinking')}
                    title="深度思考设置"
                    type="button"
                  >
                    <BrainCircuit size={15} />
                    <span className="tool-btn-label">深度思考</span>
                    <span className="tool-btn-detail">{enableThinking ? thinkingEffortLabel(effort) : '关闭'}</span>
                    <ChevronDown size={14} />
                  </button>
                ) : null}
                <button
                  aria-controls="chat-tool-drawer"
                  aria-expanded={visibleToolDrawer === 'search'}
                  className={toolButtonClass('search', enableSearch)}
                  onClick={() => toggleToolDrawer('search')}
                  disabled={!selectedProviderSupportsToolCalling}
                  title={
                    selectedProviderSupportsToolCalling
                      ? '联网搜索设置'
                      : '当前模型不支持原生工具调用'
                  }
                  type="button"
                >
                  <Sparkles size={15} />
                  <span className="tool-btn-label">联网搜索</span>
                  <span className="tool-btn-detail">{enableSearch ? selectedSearchProviderLabel : '关闭'}</span>
                  <ChevronDown size={14} />
                </button>
                <button
                  aria-controls="chat-tool-drawer"
                  aria-expanded={visibleToolDrawer === 'provider'}
                  className={toolButtonClass('provider', Boolean(selectedProviderId))}
                  disabled={!providers.length}
                  onClick={() => toggleToolDrawer('provider')}
                  title={`选择模型：${selectedProviderTitle}`}
                  aria-label={`选择模型，当前 ${selectedProviderTitle}`}
                  type="button"
                >
                  <Bot size={15} />
                  <span className="tool-btn-label model">{selectedProviderLabel}</span>
                  {selectedProvider ? <span className="tool-btn-detail model">{selectedProvider.name}</span> : null}
                  <ChevronDown size={14} />
                </button>
              </div>

              {visibleToolDrawer ? (
                <div className={`tool-drawer-card ${visibleToolDrawer}`} id="chat-tool-drawer" role="dialog" aria-label="聊天工具设置">
                  {visibleToolDrawer === 'thinking' ? (
                    <>
                      <label className="drawer-toggle-row">
                        <input
                          checked={enableThinking}
                          onChange={(event) => setEnableThinking(event.target.checked)}
                          type="checkbox"
                        />
                        <span>
                          <strong>深度思考</strong>
                          <small>{enableThinking ? thinkingEffortLabel(effort) : '关闭'}</small>
                        </span>
                      </label>
                      {enableThinking ? (
                        <div className="drawer-section">
                          <div className="drawer-section-title">思考强度</div>
                          <div className="drawer-segmented" role="group" aria-label="思考强度">
                            {thinkingEffortOptions.map((option) => (
                              <button
                                className={effort === option ? 'active' : ''}
                                key={option}
                                onClick={() => setEffort(option)}
                                type="button"
                              >
                                {thinkingEffortLabel(option)}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : null}
                    </>
                  ) : null}

                  {visibleToolDrawer === 'search' ? (
                    <>
                      <label className="drawer-toggle-row">
                        <input
                          checked={enableSearch}
                          disabled={!selectedProviderSupportsToolCalling}
                          onChange={(event) => {
                            setChatError('')
                            setEnableSearch(event.target.checked)
                          }}
                          type="checkbox"
                        />
                        <span>
                          <strong>联网搜索</strong>
                          <small>{enableSearch ? selectedSearchProviderLabel : '关闭'}</small>
                        </span>
                      </label>
                      <div className="drawer-section">
                        <div className="drawer-section-title">搜索源</div>
                        <div className="drawer-option-list">
                          {searchProviderOptions.map((option) => {
                            const status = searchProviders?.[option]
                            const label = searchProviderLabel(option)
                            const unavailable = status ? !isSearchProviderAvailable(status) : false
                            return (
                              <button
                                className={searchProvider === option ? 'drawer-option active' : 'drawer-option'}
                                disabled={unavailable}
                                key={option}
                                onClick={() => {
                                  setChatError('')
                                  setSearchProvider(option)
                                }}
                                type="button"
                              >
                                <span>
                                  <strong>{label}</strong>
                                  <small>{unavailable ? '不可用' : '可用'}</small>
                                </span>
                                {searchProvider === option ? <Check size={14} /> : null}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    </>
                  ) : null}

                  {visibleToolDrawer === 'provider' ? (
                    <div className="drawer-section provider-picker">
                      <div className="provider-picker-current">
                        <span>当前模型</span>
                        <strong>{selectedProviderLabel}</strong>
                        <small>{selectedProvider?.name ?? '未选择供应商'}</small>
                      </div>
                      <div className="provider-picker-group-list">
                        {providerGroups.length ? providerGroups.map((group) => (
                          <section className="provider-picker-group" key={group.id}>
                            <div className="provider-picker-heading">
                              <span className="provider-picker-mark"><Bot size={14} /></span>
                              <span>
                                <strong>{group.name}</strong>
                                <small>{providerApiFormatLabel(group.apiFormat)} / {group.models.length} 个模型</small>
                              </span>
                            </div>
                            <div className="provider-picker-model-list">
                              {group.models.map((provider) => (
                                <button
                                  aria-current={selectedProviderId === provider.id ? 'true' : undefined}
                                  className={selectedProviderId === provider.id ? 'drawer-option provider-model-option active' : 'drawer-option provider-model-option'}
                                  key={provider.id}
                                  onClick={() => {
                                    applyProviderSelection(provider.id)
                                    setOpenToolDrawer(null)
                                  }}
                                  title={`${provider.name} / ${provider.model_name}`}
                                  type="button"
                                >
                                  <span>
                                    <strong>{provider.model_name}</strong>
                                    <small>{modelCapabilityText(provider)}</small>
                                  </span>
                                  {selectedProviderId === provider.id ? <Check size={14} /> : null}
                                </button>
                              ))}
                            </div>
                          </section>
                        )) : (
                          <div className="drawer-empty">暂无模型</div>
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="right-tools">
                {selectedProvider?.supports_vision ? (
                  <button
                    aria-label="上传图片"
                    className="upload-btn"
                    onClick={() => {
                      setOpenToolDrawer(null)
                      triggerFileSelect()
                    }}
                    title="上传图片"
                    type="button"
                  >
                    <FileImage size={17} />
                  </button>
                ) : null}
                {chatLoading ? (
                  <button className="send-btn stop" onClick={stopStreaming} type="button">
                    <Square size={14} />
                  </button>
                ) : (
                  <button
                    aria-label={canSendMessage ? '发送消息' : '消息为空，无法发送'}
                    className="send-btn"
                    disabled={!canSendMessage}
                    title={canSendMessage ? '发送消息' : '输入消息后发送'}
                    type="submit"
                  >
                    <ArrowUp size={17} />
                  </button>
                )}
              </div>
            </div>

            <input accept="image/jpeg,image/png,image/gif,image/webp" hidden id="chat-attachments" multiple name="attachments" onChange={handleFileChange} ref={fileInputRef} type="file" />
            {chatError ? <div className="error-text">{chatError}</div> : null}
          </form>
        </div>
      </main>
    </div>
  )
}
