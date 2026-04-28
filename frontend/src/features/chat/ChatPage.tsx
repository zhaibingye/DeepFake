import { Eye, FileImage, LayoutDashboard, LogOut, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Pencil, SendHorizonal, Sparkles, Square, Trash2, UserRound, BrainCircuit } from 'lucide-react'

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
  return (
    <div className={sidebarCollapsed ? 'chat-shell sidebar-collapsed' : 'chat-shell'}>
      <aside className={sidebarCollapsed ? 'chat-sidebar collapsed' : 'chat-sidebar'}>
        <div className="sidebar-top">
          <div className="sidebar-brand">
            <div className="brand-lockup">
              {sidebarCollapsed ? (
                <div className="brand-mark solid"><DeepfakeWhaleIcon className="whale-icon" /></div>
              ) : (
                <img alt="deepfake" className="brand-logo-image" src="/deepfake-logo.png" />
              )}
            </div>
            <button aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} className="icon-btn sidebar-toggle" onClick={toggleSidebar} title={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'} type="button">
              {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          </div>

          <button
            className={sidebarCollapsed ? 'new-chat-btn icon-only' : 'new-chat-btn'}
            disabled={chatLoading}
            onClick={startNewConversation}
            title="开启新对话"
            type="button"
          >
            <MessageSquarePlus size={16} />
            {sidebarCollapsed ? null : '开启新对话'}
          </button>
        </div>

        <div className={sidebarCollapsed ? 'conversation-list collapsed' : 'conversation-list'}>
          {sidebarCollapsed ? null : <div className="section-title">7 天内</div>}
          {!sidebarCollapsed && conversations.length === 0 ? <div className="empty-tip">还没有会话，发一条消息开始。</div> : null}
          {conversations.map((conversation) => (
            <div key={conversation.id} className={activeConversationId === conversation.id ? 'conversation-item active' : 'conversation-item'}>
              <button
                className="conversation-main"
                disabled={chatLoading}
                onClick={() => void openConversation(conversation.id)}
                type="button"
              >
                <span>{sidebarCollapsed ? conversation.title.slice(0, 1) : conversation.title}</span>
                {sidebarCollapsed ? null : <small>{conversation.provider_name} / {conversation.model_name}</small>}
              </button>
              <div className={sidebarCollapsed ? 'conversation-actions hidden' : 'conversation-actions'}>
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
          <div className={sidebarCollapsed ? 'user-card compact collapsed' : 'user-card compact'}>
            <div className="user-meta">
              <div className="avatar"><UserRound size={15} /></div>
              <div className={sidebarCollapsed ? 'hidden' : ''}>
                <strong>{user.username}</strong>
                <span>{user.role === 'admin' ? '管理员' : '普通用户'}</span>
              </div>
            </div>
            <div className="user-actions">
              {user.role === 'admin' ? (
                <button className="icon-btn" onClick={navigateToAdmin} title="管理后台" type="button">
                  <LayoutDashboard size={16} />
                </button>
              ) : null}
              <button className="icon-btn" onClick={handleLogout} title="退出登录" type="button">
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

            <div className="composer-toolbar">
              <div className="left-tools">
                {selectedProvider?.supports_thinking ? (
                  <button
                    className={enableThinking ? 'tool-btn active' : 'tool-btn'}
                    onClick={() => setEnableThinking((value) => !value)}
                    type="button"
                  >
                    <BrainCircuit size={15} />
                    深度思考
                  </button>
                ) : null}
                {selectedProvider?.supports_thinking && enableThinking ? (
                  <select id="chat-thinking-effort" name="thinking_effort" value={effort} onChange={(event) => setEffort(event.target.value as ThinkingEffort)}>
                    {thinkingEffortOptions.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                ) : null}
                <button
                  className={enableSearch ? 'tool-btn active' : 'tool-btn'}
                  onClick={() => {
                    setChatError('')
                    setEnableSearch((value) => !value)
                  }}
                  disabled={!selectedProviderSupportsToolCalling}
                  title={
                    selectedProviderSupportsToolCalling
                      ? '允许模型按需使用联网搜索'
                      : '当前模型不支持原生工具调用'
                  }
                  type="button"
                >
                  <Sparkles size={15} />
                  联网搜索
                </button>
                <select
                  disabled={!enableSearch}
                  id="chat-search-provider"
                  name="search_provider"
                  value={searchProvider}
                  onChange={(event) => {
                    setChatError('')
                    setSearchProvider(event.target.value as SearchProviderKind)
                  }}
                >
                  {searchProviderOptions.map((option) => {
                    const status = searchProviders?.[option]
                    const label = searchProviderLabel(option)
                    return (
                      <option key={option} value={option}>
                        {status && !isSearchProviderAvailable(status) ? `${label}（不可用）` : label}
                      </option>
                    )
                  })}
                </select>
                <select className="provider-select inline" id="chat-provider" name="provider_id" value={selectedProviderId ?? ''} onChange={(event) => applyProviderSelection(Number(event.target.value))}>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>{provider.name} / {provider.model_name}</option>
                  ))}
                </select>
              </div>

              <div className="right-tools">
                {selectedProvider?.supports_vision ? (
                  <button className="upload-btn" onClick={triggerFileSelect} type="button">
                    <Eye size={17} />
                  </button>
                ) : null}
                {chatLoading ? (
                  <button className="send-btn stop" onClick={stopStreaming} type="button">
                    <Square size={14} />
                  </button>
                ) : (
                  <button className="send-btn" disabled={chatLoading || !selectedProviderId} type="submit">
                    <SendHorizonal size={17} />
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
