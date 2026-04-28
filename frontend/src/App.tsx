import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from './api'
import { getThinkingEffortOptions, resolveAuthMode } from './appState'
import type { AuthMode } from './appState'
import './App.css'
import { AdminPage, type AdminSection } from './features/admin/AdminPage'
import {
  buildSearchProviderForms,
  buildEditingProviderForm,
  loadAdminDataState,
  removeAdminUserState,
  removeProviderState,
  resetAdminUserPasswordState,
  submitSearchProviderState,
  submitAdminProfileState,
  submitAdminUserState,
  submitProviderState,
  toggleAllowRegistrationState,
  toggleUserEnabledState,
} from './features/admin/controller'
import type { SearchProviderFormState } from './features/admin/controller'
import { defaultProviderForm } from './features/admin/providerForm'
import { AuthPage } from './features/auth/AuthPage'
import { authenticateUserState, refreshAuthSurfaceState } from './features/auth/authState'
import { ModalDialog, type DialogState } from './features/common/ModalDialog'
import { ChatPage } from './features/chat/ChatPage'
import {
  applyProviderSelectionState,
  loadConversationsForSessionState,
  loadConversationsState,
  loadProvidersState,
  loadSearchProvidersState,
  openConversationState,
  sendMessageState,
  startNewConversationState,
} from './features/chat/controller'
import type { SearchProviderLoadState } from './features/chat/searchProviders'
import { useTimelineState } from './components/chat/useTimelineState.ts'
import type {
  AdminManagedUser,
  AdminSettings,
  Attachment,
  ChatDonePayload,
  Conversation,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
  SetupStatus,
  ThinkingEffort,
  User,
} from './types'
import { fileToAttachment } from './utils'

type AppRoute = 'chat' | 'admin'

function getRouteFromLocation(): AppRoute {
  return window.location.pathname.startsWith('/admin') ? 'admin' : 'chat'
}

function getAdminSectionFromLocation(): AdminSection {
  if (window.location.pathname.startsWith('/admin/providers')) return 'providers'
  if (window.location.pathname.startsWith('/admin/search-mcp')) return 'search-mcp'
  if (window.location.pathname.startsWith('/admin/users')) return 'users'
  return 'overview'
}

function getAdminPath(section: AdminSection): string {
  if (section === 'providers') return '/admin/providers'
  if (section === 'search-mcp') return '/admin/search-mcp'
  if (section === 'users') return '/admin/users'
  return '/admin'
}

function App() {
  const [route, setRoute] = useState<AppRoute>(() => getRouteFromLocation())
  const [adminSection, setAdminSection] = useState<AdminSection>(() => getAdminSectionFromLocation())
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebar-collapsed') === '1')
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [user, setUser] = useState<User | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [setupPasswordConfirm, setSetupPasswordConfirm] = useState('')
  const [authError, setAuthError] = useState('')
  const [loadingAuth, setLoadingAuth] = useState(false)
  const [publicAuthSettings, setPublicAuthSettings] = useState<AdminSettings>({ allow_registration: true })
  const [setupStatus, setSetupStatus] = useState<SetupStatus>({ needs_admin_setup: false })
  const [setupStatusLoaded, setSetupStatusLoaded] = useState(false)

  const [providers, setProviders] = useState<Provider[]>([])
  const [adminProviders, setAdminProviders] = useState<Provider[]>([])
  const [adminSearchProviders, setAdminSearchProviders] = useState<SearchProviderAvailability | null>(null)
  const [adminUsers, setAdminUsers] = useState<AdminManagedUser[]>([])
  const [adminSettings, setAdminSettings] = useState<AdminSettings>({ allow_registration: true })
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null)
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<ChatDonePayload['messages']>([])
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [enableThinking, setEnableThinking] = useState(true)
  const [enableSearch, setEnableSearch] = useState(false)
  const [searchProvider, setSearchProvider] = useState<SearchProviderKind>('exa')
  const [searchProviders, setSearchProviders] = useState<SearchProviderAvailability | null>(null)
  const [searchProviderLoadState, setSearchProviderLoadState] = useState<SearchProviderLoadState>('loading')
  const [effort, setEffort] = useState<ThinkingEffort>('high')
  const [chatError, setChatError] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const streamingTimeline = useTimelineState()
  const [pendingUserMessage, setPendingUserMessage] = useState<{ text: string; attachments: Attachment[]; createdAt: string } | null>(null)
  const [providerForm, setProviderForm] = useState(defaultProviderForm)
  const [providerSuccess, setProviderSuccess] = useState('')
  const [providerError, setProviderError] = useState('')
  const [searchProviderForms, setSearchProviderForms] = useState<Record<SearchProviderKind, SearchProviderFormState>>({
    exa: { api_key: '', is_enabled: true },
    tavily: { api_key: '', is_enabled: false },
  })
  const [searchProviderMessage, setSearchProviderMessage] = useState('')
  const [searchProviderError, setSearchProviderError] = useState(false)
  const [editingProviderId, setEditingProviderId] = useState<number | null>(null)
  const [adminProfile, setAdminProfile] = useState({ username: 'admin', current_password: '', new_password: '' })
  const [adminProfileMessage, setAdminProfileMessage] = useState('')
  const [userForm, setUserForm] = useState({ username: '', password: '', role: 'user' as 'admin' | 'user', is_enabled: true })
  const [userSearch, setUserSearch] = useState('')
  const [userAdminMessage, setUserAdminMessage] = useState('')
  const [userAdminError, setUserAdminError] = useState(false)
  const [dialogState, setDialogState] = useState<DialogState | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const messageEndRef = useRef<HTMLDivElement | null>(null)
  const shouldFollowStreamRef = useRef(true)
  const streamAbortRef = useRef<AbortController | null>(null)
  const authSessionVersionRef = useRef(0)
  const routeRef = useRef<AppRoute>(route)
  const providersRef = useRef<Provider[]>(providers)
  const selectedProviderIdRef = useRef<number | null>(selectedProviderId)
  const composerStateRef = useRef({
    effort,
    enableThinking,
    enableSearch,
    attachments,
  })

  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) ?? null
  const currentConversation =
    activeConversation ?? conversations.find((conversation) => conversation.id === activeConversationId) ?? null
  const currentConversationProvider =
    providers.find((provider) => provider.id === currentConversation?.provider_id) ?? null
  const selectedProviderSupportsToolCalling = Boolean(
    selectedProvider?.supports_tool_calling
      && (
        selectedProvider.api_format === 'anthropic_messages'
        || selectedProvider.api_format === 'openai_chat'
        || selectedProvider.api_format === 'deepseek_chat'
        || selectedProvider.api_format === 'siliconflow_chat'
        || selectedProvider.api_format === 'openai_responses'
        || selectedProvider.api_format === 'gemini'
      ),
  )
  const selectedSearchProviderStatus = searchProviders?.[searchProvider] ?? null
  const isAdminRoute = route === 'admin'
  const hasVisibleConversation = messages.length > 0 || !!pendingUserMessage || streamingTimeline.parts.length > 0
  const hasStreamingTimelineParts = streamingTimeline.parts.length > 0
  const effectiveAuthMode = resolveAuthMode(authMode, publicAuthSettings.allow_registration)
  const providerThinkingEffortOptions = getThinkingEffortOptions(providerForm.api_format)
  const chatThinkingEffortOptions = getThinkingEffortOptions(selectedProvider?.api_format)
  const providerApiUrlPlaceholder =
    providerForm.api_format === 'openai_chat' || providerForm.api_format === 'openai_responses'
      ? 'https://api.openai.com/v1'
      : providerForm.api_format === 'deepseek_chat'
        ? 'https://api.deepseek.com'
        : providerForm.api_format === 'siliconflow_chat'
          ? 'https://api.siliconflow.cn/v1'
          : providerForm.api_format === 'gemini'
            ? 'https://generativelanguage.googleapis.com/v1beta'
            : 'https://.../anthropic/v1'
  const filteredAdminUsers = adminUsers.filter((managedUser) => {
    const keyword = userSearch.trim().toLowerCase()
    if (!keyword) return true
    return managedUser.username.toLowerCase().includes(keyword)
  })

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', next ? '1' : '0')
      return next
    })
  }, [])

  const navigateTo = useCallback((nextRoute: AppRoute, replace = false) => {
    const nextPath = nextRoute === 'admin' ? getAdminPath('overview') : '/'
    if (window.location.pathname !== nextPath) {
      const method = replace ? 'replaceState' : 'pushState'
      window.history[method](null, '', nextPath)
    }
    setRoute(nextRoute)
    if (nextRoute === 'admin') {
      setAdminSection('overview')
    }
  }, [])

  const navigateToAdminSection = useCallback((nextSection: AdminSection, replace = false) => {
    const nextPath = getAdminPath(nextSection)
    if (window.location.pathname !== nextPath) {
      const method = replace ? 'replaceState' : 'pushState'
      window.history[method](null, '', nextPath)
    }
    setRoute('admin')
    setAdminSection(nextSection)
  }, [])

  function closeDialog(result: boolean | string | null) {
    setDialogState((current) => {
      current?.resolve(result)
      return null
    })
  }

  function stopStreaming() {
    streamAbortRef.current?.abort()
    streamAbortRef.current = null
  }

  function resetSearchState() {
    setEnableSearch(false)
    setSearchProvider('exa')
    setSearchProviders(null)
    setSearchProviderLoadState('loading')
  }

  function openConfirmDialog(title: string, message: string, confirmLabel = '确认', cancelLabel = '取消') {
    return new Promise<boolean>((resolve) => {
      setDialogState({
        mode: 'confirm',
        title,
        message,
        confirmLabel,
        cancelLabel,
        value: '',
        resolve: (value) => resolve(value === true),
      })
    })
  }

  function openPromptDialog(title: string, message: string, initialValue: string, confirmLabel = '保存', cancelLabel = '取消') {
    return new Promise<string | null>((resolve) => {
      setDialogState({
        mode: 'prompt',
        title,
        message,
        confirmLabel,
        cancelLabel,
        value: initialValue,
        resolve: (value) => resolve(typeof value === 'string' ? value : null),
      })
    })
  }

  function triggerSendMessage() {
    window.setTimeout(() => {
      void sendMessage()
    }, 0)
  }

  const applyProviderSelection = useCallback((nextProviderId: number | null, providerList = providersRef.current) => {
    applyProviderSelectionState({
      nextProviderId,
      providerList,
      composerState: composerStateRef.current,
      setSelectedProviderId,
      setEffort,
      setEnableThinking,
      setEnableSearch,
      setAttachments,
      selectedProviderIdRef,
      composerStateRef,
    })
  }, [])

  useEffect(() => {
    if (!shouldFollowStreamRef.current) {
      return
    }
    messageEndRef.current?.scrollIntoView({ behavior: hasStreamingTimelineParts ? 'auto' : 'smooth' })
  }, [hasStreamingTimelineParts, messages, streamingTimeline.revision])

  useEffect(() => {
    routeRef.current = route
  }, [route])

  useEffect(() => {
    providersRef.current = providers
  }, [providers])

  useEffect(() => {
    selectedProviderIdRef.current = selectedProviderId
  }, [selectedProviderId])

  useEffect(() => {
    composerStateRef.current = {
      effort,
      enableThinking,
      enableSearch,
      attachments,
    }
  }, [attachments, effort, enableSearch, enableThinking])

  useEffect(() => {
    const handleScroll = () => {
      const root = document.documentElement
      const distanceToBottom = root.scrollHeight - window.scrollY - window.innerHeight
      shouldFollowStreamRef.current = distanceToBottom < 80
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    const handlePopState = () => {
      const nextRoute = getRouteFromLocation()
      if (nextRoute === 'admin' && user?.role !== 'admin') {
        window.history.replaceState(null, '', '/')
        setRoute('chat')
        setAdminSection('overview')
        return
      }
      setRoute(nextRoute)
      setAdminSection(getAdminSectionFromLocation())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [user?.role])

  const loadProviders = useCallback(async (currentToken = token) => {
    if (!currentToken) return
    await loadProvidersState({
      token: currentToken,
      providersRef,
      selectedProviderIdRef,
      setProviders,
      applyProviderSelection,
    })
  }, [applyProviderSelection, token])

  const loadSearchProviders = useCallback(async () => {
    await loadSearchProvidersState({
      setSearchProviderLoadState,
      setSearchProviders,
    })
  }, [])

  const loadConversations = useCallback(async (currentToken = token) => {
    if (!currentToken) return
    await loadConversationsState(currentToken, {
      setConversations,
      setActiveConversation,
    })
  }, [token])

  const loadConversationsForSession = useCallback(async (currentToken: string, sessionVersion: number) => {
    return loadConversationsForSessionState({
      token: currentToken,
      sessionVersion,
      authSessionVersionRef,
      setConversations,
      setActiveConversation,
    })
  }, [])

  const loadAdminData = useCallback(async (currentToken = token, role = user?.role) => {
    if (!currentToken || role !== 'admin') return
    await loadAdminDataState({
      token: currentToken,
      role,
      setAdminProviders,
      setAdminSearchProviders,
      setSearchProviderForms,
      setAdminUsers,
      setAdminSettings,
    })
  }, [token, user?.role])

  const refreshAuthSurface = useCallback(async () => {
    try {
      const { settings, setupStatus: nextSetupStatus } = await refreshAuthSurfaceState()
      setPublicAuthSettings(settings)
      setSetupStatus(nextSetupStatus)
    } finally {
      setSetupStatusLoaded(true)
    }
  }, [])

  const bootstrap = useCallback(async (currentToken: string) => {
    try {
      const me = await api.me(currentToken)
      setSetupStatus({ needs_admin_setup: false })
      setUser(me)
      if (me.role === 'admin') {
        setAdminProfile((prev) => ({ ...prev, username: me.username }))
      }
      await Promise.all([loadProviders(currentToken), loadConversations(currentToken)])
      if (me.role === 'admin') {
        try {
          await loadAdminData(currentToken, me.role)
        } catch {
          setAdminProviders([])
          setAdminSearchProviders(null)
          setSearchProviderForms(buildSearchProviderForms({
            exa: { is_enabled: true, is_configured: true },
            tavily: { is_enabled: false, is_configured: false },
          }))
          setAdminUsers([])
          setAdminSettings({ allow_registration: true })
        }
      }
      if (routeRef.current === 'admin' && me.role !== 'admin') {
        navigateTo('chat', true)
      }
    } catch {
      localStorage.removeItem('token')
      navigateTo('chat', true)
      setToken(null)
      setUser(null)
      setProviders([])
      setAdminProviders([])
      setAdminSearchProviders(null)
      setAdminUsers([])
      setAdminSettings({ allow_registration: true })
      setConversations([])
      setActiveConversation(null)
      setMessages([])
      setActiveConversationId(null)
      applyProviderSelection(null)
      setAttachments([])
      setInput('')
      resetSearchState()
      setPendingUserMessage(null)
      void refreshAuthSurface()
    }
  }, [applyProviderSelection, loadAdminData, loadConversations, loadProviders, navigateTo, refreshAuthSurface])

  useEffect(() => {
    void refreshAuthSurface()
  }, [refreshAuthSurface])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadSearchProviders().catch(() => undefined)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadSearchProviders, token])

  useEffect(() => {
    if (!token) {
      return
    }
    const timer = window.setTimeout(() => {
      void bootstrap(token)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [bootstrap, token])

  async function handleAuthSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (setupStatus.needs_admin_setup) {
      const username = authUsername.trim()
      if (username.length < 3 || username.length > 32) {
        setAuthError('用户名需要为 3 到 32 个字符。')
        return
      }
      if (authPassword.length < 6 || authPassword.length > 128) {
        setAuthError('密码需要为 6 到 128 个字符。')
        return
      }
      if (authPassword !== setupPasswordConfirm) {
        setAuthError('两次输入的密码不一致。')
        return
      }
    }
    setLoadingAuth(true)
    setAuthError('')
    try {
      const result = await authenticateUserState({
        needsAdminSetup: setupStatus.needs_admin_setup,
        authMode: effectiveAuthMode,
        username: authUsername,
        password: authPassword,
      })
      localStorage.setItem('token', result.token)
      setToken(result.token)
      setUser(result.user)
      setSetupStatus({ needs_admin_setup: false })
      setAuthPassword('')
      setSetupPasswordConfirm('')
      navigateTo('chat', true)
    } catch (error) {
      const message = error instanceof Error ? error.message : '认证失败'
      setAuthError(message === '账号已停用' ? '账号已被管理员停用，请联系管理员处理。' : message)
      void refreshAuthSurface().catch(() => undefined)
    } finally {
      setLoadingAuth(false)
    }
  }

  const handleLogout = useCallback((callApi = true) => {
    authSessionVersionRef.current += 1
    stopStreaming()
    const currentToken = token
    if (callApi && currentToken) {
      void api.logout(currentToken).catch(() => undefined)
    }
    localStorage.removeItem('token')
    navigateTo('chat', true)
    setToken(null)
    setUser(null)
    setProviders([])
    setAdminProviders([])
    setAdminSearchProviders(null)
    setAdminUsers([])
    setConversations([])
    setActiveConversation(null)
    setMessages([])
    setActiveConversationId(null)
    applyProviderSelection(null)
    setAttachments([])
    setChatLoading(false)
    streamingTimeline.reset()
    setInput('')
    resetSearchState()
    setPendingUserMessage(null)
    void refreshAuthSurface().catch(() => undefined)
  }, [applyProviderSelection, navigateTo, refreshAuthSurface, streamingTimeline, token])

  async function openConversation(conversationId: number) {
    if (!token || chatLoading) return
    await openConversationState({
      token,
      conversationId,
      chatLoading,
      conversations,
      shouldFollowStreamRef,
      setActiveConversationId,
      setActiveConversation,
      applyProviderSelection,
      setMessages,
      streamingTimeline,
      setPendingUserMessage,
      route,
      navigateTo,
    })
  }

  const startNewConversation = useCallback(() => {
    startNewConversationState({
      chatLoading,
      shouldFollowStreamRef,
      setActiveConversationId,
      setActiveConversation,
      setMessages,
      setInput,
      setAttachments,
      setChatError,
      streamingTimeline,
      setPendingUserMessage,
      route,
      navigateTo,
    })
  }, [chatLoading, navigateTo, route, streamingTimeline])

  async function sendMessage() {
    if (!token) return
    await sendMessageState({
      token,
      selectedProviderId,
      chatLoading,
      authSessionVersionRef,
      enableSearch,
      selectedProviderSupportsToolCalling,
      searchProvider,
      selectedSearchProviderStatus,
      searchProviderLoadState,
      setChatError,
      input,
      attachments,
      activeConversationId,
      activeConversation,
      messages,
      setChatLoading,
      streamingTimeline,
      setInput,
      setAttachments,
      setPendingUserMessage,
      shouldFollowStreamRef,
      streamAbortRef,
      selectedProvider,
      enableThinking,
      effort,
      setActiveConversationId,
      setActiveConversation,
      setMessages,
      loadConversationsForSession,
    })
  }

  async function handleSendMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    triggerSendMessage()
  }

  function handleComposerKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }
    event.preventDefault()
    triggerSendMessage()
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    if (!files.length) return
    const mapped = await Promise.all(files.map((file) => fileToAttachment(file)))
    setAttachments(mapped)
    event.target.value = ''
  }

  function removeAttachment(name: string) {
    setAttachments((prev) => prev.filter((attachment) => attachment.name !== name))
  }

  async function submitProvider(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    await submitProviderState({
      token,
      editingProviderId,
      providerForm,
      setProviderError,
      setProviderSuccess,
      setProviderForm,
      setEditingProviderId,
      refreshAfterSave: async () => {
        await Promise.all([loadProviders(token), loadAdminData(token, 'admin')])
      },
    })
  }

  async function removeProvider(provider: Provider) {
    if (!token) return
    await removeProviderState({
      token,
      provider,
      selectedProviderId,
      applyProviderSelection,
      confirmDelete: () => openConfirmDialog('删除供应商', `确认删除供应商“${provider.name}”吗？`, '删除'),
      setProviderError,
      setProviderSuccess,
      refreshAfterDelete: async () => {
        await Promise.all([loadProviders(token), loadAdminData(token, 'admin')])
      },
    })
  }

  function editProvider(provider: Provider) {
    setEditingProviderId(provider.id)
    setProviderForm(buildEditingProviderForm(provider))
    navigateToAdminSection('providers')
  }

  function cancelEditingProvider() {
    setEditingProviderId(null)
    setProviderForm(defaultProviderForm)
  }

  async function submitAdminProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    await submitAdminProfileState({
      token,
      adminProfile,
      setUser,
      setAdminProfile,
      setAdminProfileMessage,
    })
  }

  async function submitSearchProvider(kind: SearchProviderKind, event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    await submitSearchProviderState({
      token,
      kind,
      form: searchProviderForms[kind],
      setAdminSearchProviders,
      setSearchProviderForms,
      setMessage: setSearchProviderMessage,
      setError: setSearchProviderError,
    })
    await loadSearchProviders().catch(() => undefined)
  }

  async function toggleAllowRegistration(value: boolean) {
    if (!token) return
    await toggleAllowRegistrationState({
      token,
      value,
      setAdminSettings,
      setUserAdminMessage,
      setUserAdminError,
    })
  }

  async function submitAdminUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    await submitAdminUserState({
      token,
      userForm,
      setAdminUsers,
      setUserForm,
      setUserAdminMessage,
      setUserAdminError,
    })
  }

  async function toggleUserEnabled(targetUser: AdminManagedUser) {
    if (!token) return
    await toggleUserEnabledState({
      token,
      targetUser,
      currentUserId: user?.id,
      onSelfDisabled: () => handleLogout(false),
      setAdminUsers,
      setUserAdminMessage,
      setUserAdminError,
    })
  }

  async function removeAdminUser(targetUser: AdminManagedUser) {
    if (!token) return
    await removeAdminUserState({
      token,
      targetUser,
      confirmDelete: () =>
        openConfirmDialog('删除用户', `确认删除用户“${targetUser.username}”吗？这会同时删除其会话记录。`, '删除'),
      setAdminUsers,
      setUserAdminMessage,
      setUserAdminError,
    })
  }

  async function resetAdminUserPassword(targetUser: AdminManagedUser) {
    if (!token) return
    const password = (await openPromptDialog('重置用户密码', `输入用户“${targetUser.username}”的新密码`, '', '重置密码'))?.trim()
    if (!password) return
    await resetAdminUserPasswordState({
      token,
      targetUser,
      password,
      setUserAdminMessage,
      setUserAdminError,
    })
  }

  async function renameConversation(conversation: Conversation) {
    if (!token) return
    const title = (await openPromptDialog('重命名会话', '输入新的会话标题', conversation.title))?.trim()
    if (!title) return
    try {
      const updated = await api.renameConversation(token, conversation.id, title)
      setConversations((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setActiveConversation((prev) => (prev?.id === updated.id ? { ...prev, ...updated } : prev))
    } catch (error) {
      setChatError(error instanceof Error ? error.message : '重命名失败')
    }
  }

  async function removeConversation(conversation: Conversation) {
    if (!token) return
    const confirmed = await openConfirmDialog('删除会话', `确认删除会话“${conversation.title}”吗？`, '删除')
    if (!confirmed) return
    try {
      await api.deleteConversation(token, conversation.id)
      setConversations((prev) => prev.filter((item) => item.id !== conversation.id))
      if (activeConversationId === conversation.id) {
        startNewConversation()
      }
    } catch (error) {
      setChatError(error instanceof Error ? error.message : '删除会话失败')
    }
  }

  if (!token || !user) {
    return (
      <>
        <AuthPage
          authMode={authMode}
          effectiveAuthMode={effectiveAuthMode}
          authUsername={authUsername}
          authPassword={authPassword}
          setupPasswordConfirm={setupPasswordConfirm}
          authError={authError}
          loadingAuth={loadingAuth}
          publicAuthSettings={publicAuthSettings}
          setupStatus={setupStatus}
          setupStatusLoaded={setupStatusLoaded}
          setAuthMode={setAuthMode}
          setAuthUsername={setAuthUsername}
          setAuthPassword={setAuthPassword}
          setSetupPasswordConfirm={setSetupPasswordConfirm}
          onSubmit={handleAuthSubmit}
        />
        {dialogState ? <ModalDialog closeDialog={closeDialog} dialogState={dialogState} setDialogState={setDialogState} /> : null}
      </>
    )
  }

  if (isAdminRoute && user.role === 'admin') {
    return (
      <>
        <AdminPage
          adminSection={adminSection}
          adminProviders={adminProviders}
          adminSearchProviders={adminSearchProviders}
          adminUsers={adminUsers}
          adminSettings={adminSettings}
          adminProfile={adminProfile}
          adminProfileMessage={adminProfileMessage}
          userForm={userForm}
          userSearch={userSearch}
          userAdminMessage={userAdminMessage}
          userAdminError={userAdminError}
          editingProviderId={editingProviderId}
          providerForm={providerForm}
          providerError={providerError}
          providerSuccess={providerSuccess}
          searchProviderForms={searchProviderForms}
          searchProviderMessage={searchProviderMessage}
          searchProviderError={searchProviderError}
          providerApiUrlPlaceholder={providerApiUrlPlaceholder}
          thinkingEffortOptions={providerThinkingEffortOptions}
          filteredAdminUsers={filteredAdminUsers}
          navigateToChat={() => navigateTo('chat')}
          handleLogout={() => handleLogout()}
          navigateToAdminSection={navigateToAdminSection}
          onSubmitAdminProfile={submitAdminProfile}
          onSubmitProvider={submitProvider}
          onSubmitSearchProvider={submitSearchProvider}
          onSubmitAdminUser={submitAdminUser}
          setAdminProfile={setAdminProfile}
          setProviderForm={setProviderForm}
          setSearchProviderForms={setSearchProviderForms}
          cancelEditingProvider={cancelEditingProvider}
          editProvider={editProvider}
          removeProvider={removeProvider}
          toggleAllowRegistration={toggleAllowRegistration}
          setUserForm={setUserForm}
          setUserSearch={setUserSearch}
          resetAdminUserPassword={resetAdminUserPassword}
          toggleUserEnabled={toggleUserEnabled}
          removeAdminUser={removeAdminUser}
        />
        {dialogState ? <ModalDialog closeDialog={closeDialog} dialogState={dialogState} setDialogState={setDialogState} /> : null}
      </>
    )
  }

  return (
    <>
      <ChatPage
        sidebarCollapsed={sidebarCollapsed}
        chatLoading={chatLoading}
        conversations={conversations}
        activeConversationId={activeConversationId}
        currentConversation={currentConversation}
        currentConversationProvider={currentConversationProvider}
        selectedProvider={selectedProvider}
        selectedProviderId={selectedProviderId}
        providers={providers}
        user={user}
        hasVisibleConversation={hasVisibleConversation}
        messages={messages}
        pendingUserMessage={pendingUserMessage}
        streamingTimeline={streamingTimeline}
        messageEndRef={messageEndRef}
        fileInputRef={fileInputRef}
        input={input}
        attachments={attachments}
        enableThinking={enableThinking}
        enableSearch={enableSearch}
        searchProvider={searchProvider}
        searchProviders={searchProviders}
        effort={effort}
        thinkingEffortOptions={chatThinkingEffortOptions}
        chatError={chatError}
        selectedProviderSupportsToolCalling={selectedProviderSupportsToolCalling}
        toggleSidebar={toggleSidebar}
        startNewConversation={startNewConversation}
        openConversation={openConversation}
        renameConversation={renameConversation}
        removeConversation={removeConversation}
        navigateToAdmin={() => navigateTo('admin')}
        handleLogout={() => handleLogout()}
        onSubmit={handleSendMessage}
        setInput={setInput}
        handleComposerKeyDown={handleComposerKeyDown}
        removeAttachment={removeAttachment}
        setEnableThinking={setEnableThinking}
        setEnableSearch={setEnableSearch}
        setChatError={setChatError}
        setSearchProvider={setSearchProvider}
        applyProviderSelection={applyProviderSelection}
        triggerFileSelect={() => fileInputRef.current?.click()}
        stopStreaming={stopStreaming}
        handleFileChange={handleFileChange}
        setEffort={setEffort}
      />
      {dialogState ? <ModalDialog closeDialog={closeDialog} dialogState={dialogState} setDialogState={setDialogState} /> : null}
    </>
  )
}

export default App
