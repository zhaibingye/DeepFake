import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import {
  Bot,
  BrainCircuit,
  Eye,
  FileImage,
  LayoutDashboard,
  LogOut,
  MessageSquarePlus,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  SendHorizonal,
  Settings,
  Shield,
  Sparkles,
  Trash2,
  UserRound,
} from 'lucide-react'
import { api } from './api'
import { MarkdownView } from './components/MarkdownView'
import './App.css'
import type { AdminManagedUser, AdminSettings, Attachment, Conversation, Message, Provider, User } from './types'
import { fileToAttachment, formatDateTime, messageImages, messagePlainText } from './utils'

type AuthMode = 'login' | 'register'
type AppRoute = 'chat' | 'admin'
type DialogState = {
  mode: 'confirm' | 'prompt'
  title: string
  message: string
  confirmLabel: string
  cancelLabel: string
  value: string
  resolve: (value: boolean | string | null) => void
}

const defaultProviderForm = {
  name: '',
  api_url: '',
  api_key: '',
  model_name: '',
  supports_thinking: true,
  supports_vision: false,
  thinking_effort: 'high',
  max_context_window: 256000,
  max_output_tokens: 32000,
  is_enabled: true,
}

function DeepfakeWhaleIcon({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 34 24" fill="none">
      <path
        fill="currentColor"
        d="M33.615 2.598c-.36-.176-.515.16-.726.33-.072.055-.132.127-.193.193-.526.562-1.14.93-1.943.887-1.174-.067-2.176.302-3.062 1.2-.188-1.107-.814-1.767-1.766-2.191-.498-.22-1.002-.441-1.35-.92-.244-.341-.31-.721-.433-1.096-.077-.226-.154-.457-.415-.496-.282-.044-.393.193-.504.391-.443.81-.614 1.702-.598 2.605.04 2.033.898 3.652 2.603 4.803.193.132.243.264.182.457-.116.397-.254.782-.376 1.179-.078.253-.194.308-.465.198-.936-.391-1.744-.97-2.458-1.669-1.213-1.173-2.31-2.467-3.676-3.48a16.254 16.254 0 0 0-.975-.668c-1.395-1.354.183-2.467.548-2.599.382-.138.133-.612-1.102-.606-1.234.005-2.364.42-3.803.97a4.34 4.34 0 0 1-.66.193 13.577 13.577 0 0 0-4.08-.143c-2.667.297-4.799 1.558-6.365 3.712C.116 8.436-.327 11.378.215 14.444c.57 3.233 2.22 5.91 4.755 8.002 2.63 2.17 5.658 3.233 9.113 3.03 2.098-.122 4.434-.403 7.07-2.633.664.33 1.362.463 2.518.562.892.083 1.75-.044 2.414-.182 1.04-.22.97-1.184.593-1.36-3.05-1.421-2.38-.843-2.99-1.311 1.55-1.834 3.918-5.093 4.648-9.531.072-.49.164-1.18.153-1.577-.006-.242.05-.336.326-.364a5.903 5.903 0 0 0 2.187-.672c1.977-1.08 2.774-2.853 2.962-4.978.028-.325-.006-.661-.35-.832ZM16.39 21.73c-2.956-2.324-4.39-3.089-4.982-3.056-.554.033-.454.667-.332 1.08.127.407.293.688.526 1.046.16.237.271.59-.161.854-.952.589-2.607-.198-2.685-.237-1.927-1.134-3.537-2.632-4.673-4.68-1.096-1.972-1.733-4.087-1.838-6.345-.028-.545.133-.738.676-.837A6.643 6.643 0 0 1 5.086 9.5c3.017.441 5.586 1.79 7.74 3.927 1.229 1.217 2.159 2.671 3.116 4.092 1.02 1.509 2.115 2.946 3.51 4.125.494.413.887.727 1.263.958-1.135.127-3.028.154-4.324-.87v-.002Zm1.417-9.114a.434.434 0 0 1 .587-.408c.06.022.117.055.16.105a.426.426 0 0 1 .122.303.434.434 0 0 1-.437.435.43.43 0 0 1-.432-.435Zm4.402 2.257c-.283.116-.565.215-.836.226-.421.022-.88-.149-1.13-.358-.387-.325-.664-.506-.78-1.073-.05-.242-.022-.617.022-.832.1-.463-.011-.76-.338-1.03-.265-.22-.603-.28-.974-.28a.8.8 0 0 1-.36-.11c-.155-.078-.283-.27-.161-.508.039-.077.227-.264.271-.297.504-.286 1.085-.193 1.623.022.498.204.875.578 1.417 1.107.553.639.653.815.968 1.295.25.374.476.76.632 1.2.094.275-.028.5-.354.638Z"
      />
    </svg>
  )
}

function getRouteFromLocation(): AppRoute {
  return window.location.pathname.startsWith('/admin') ? 'admin' : 'chat'
}

function App() {
  const [route, setRoute] = useState<AppRoute>(() => getRouteFromLocation())
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebar-collapsed') === '1')
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('token'))
  const [user, setUser] = useState<User | null>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [loadingAuth, setLoadingAuth] = useState(false)
  const [publicAuthSettings, setPublicAuthSettings] = useState<AdminSettings>({ allow_registration: true })

  const [providers, setProviders] = useState<Provider[]>([])
  const [adminProviders, setAdminProviders] = useState<Provider[]>([])
  const [adminUsers, setAdminUsers] = useState<AdminManagedUser[]>([])
  const [adminSettings, setAdminSettings] = useState<AdminSettings>({ allow_registration: true })
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null)
  const [activeConversation, setActiveConversation] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedProviderId, setSelectedProviderId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [enableThinking, setEnableThinking] = useState(true)
  const [effort, setEffort] = useState<'low' | 'medium' | 'high' | 'max'>('high')
  const [chatError, setChatError] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [streamingAssistant, setStreamingAssistant] = useState<{ text: string; thinking: string } | null>(null)
  const [pendingUserMessage, setPendingUserMessage] = useState<{ text: string; attachments: Attachment[]; createdAt: string } | null>(null)
  const [providerForm, setProviderForm] = useState(defaultProviderForm)
  const [providerSuccess, setProviderSuccess] = useState('')
  const [providerError, setProviderError] = useState('')
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

  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) ?? null
  const currentConversation =
    activeConversation ?? conversations.find((conversation) => conversation.id === activeConversationId) ?? null
  const currentConversationProvider =
    providers.find((provider) => provider.id === currentConversation?.provider_id) ?? null
  const isAdminRoute = route === 'admin'
  const hasVisibleConversation = messages.length > 0 || !!pendingUserMessage || !!streamingAssistant
  const filteredAdminUsers = adminUsers.filter((managedUser) => {
    const keyword = userSearch.trim().toLowerCase()
    if (!keyword) return true
    return managedUser.username.toLowerCase().includes(keyword)
  })

  function toggleSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', next ? '1' : '0')
      return next
    })
  }

  function navigateTo(nextRoute: AppRoute, replace = false) {
    const nextPath = nextRoute === 'admin' ? '/admin' : '/'
    if (window.location.pathname !== nextPath) {
      const method = replace ? 'replaceState' : 'pushState'
      window.history[method](null, '', nextPath)
    }
    setRoute(nextRoute)
  }

  function closeDialog(result: boolean | string | null) {
    setDialogState((current) => {
      current?.resolve(result)
      return null
    })
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

  useEffect(() => {
    if (!shouldFollowStreamRef.current) {
      return
    }
    messageEndRef.current?.scrollIntoView({ behavior: streamingAssistant ? 'auto' : 'smooth' })
  }, [messages, streamingAssistant])

  useEffect(() => {
    const handleScroll = () => updateFollowStreamState()
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  useEffect(() => {
    const handlePopState = () => setRoute(getRouteFromLocation())
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    void api.authSettings().then(setPublicAuthSettings).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!selectedProvider) {
      return
    }
    setEffort(selectedProvider.thinking_effort)
    if (!selectedProvider.supports_thinking) {
      setEnableThinking(false)
    }
    if (!selectedProvider.supports_vision) {
      setAttachments([])
    }
  }, [selectedProvider])

  useEffect(() => {
    if (!publicAuthSettings.allow_registration && authMode === 'register') {
      setAuthMode('login')
    }
  }, [authMode, publicAuthSettings.allow_registration])

  useEffect(() => {
    if (route === 'admin' && user?.role !== 'admin') {
      navigateTo('chat', true)
    }
  }, [route, user?.role])

  const loadProviders = useCallback(async (currentToken = token) => {
    if (!currentToken) return
    const list = await api.listProviders(currentToken)
    setProviders(list)
    setSelectedProviderId((prev) => (prev && list.some((provider) => provider.id === prev) ? prev : list[0]?.id ?? null))
  }, [token])

  const loadConversations = useCallback(async (currentToken = token) => {
    if (!currentToken) return
    const list = await api.listConversations(currentToken)
    setConversations(list)
    setActiveConversation((prev) => {
      if (!prev) return prev
      return list.find((item) => item.id === prev.id) ?? prev
    })
  }, [token])

  const loadAdminData = useCallback(async (currentToken = token, role = user?.role) => {
    if (!currentToken || role !== 'admin') return
    const [providersList, usersList, settings] = await Promise.all([
      api.listAdminProviders(currentToken),
      api.listAdminUsers(currentToken),
      api.getAdminSettings(currentToken),
    ])
    setAdminProviders(providersList)
    setAdminUsers(usersList)
    setAdminSettings(settings)
  }, [token, user?.role])

  const bootstrap = useCallback(async (currentToken: string) => {
    try {
      const me = await api.me(currentToken)
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
          setAdminUsers([])
          setAdminSettings({ allow_registration: true })
        }
      }
      if (route === 'admin' && me.role !== 'admin') {
        navigateTo('chat', true)
      }
    } catch {
      localStorage.removeItem('token')
      navigateTo('chat', true)
      setToken(null)
      setUser(null)
      setProviders([])
      setAdminProviders([])
      setAdminUsers([])
      setAdminSettings({ allow_registration: true })
      setConversations([])
      setActiveConversation(null)
      setMessages([])
      setActiveConversationId(null)
      setSelectedProviderId(null)
      setAttachments([])
      setInput('')
      setPendingUserMessage(null)
    }
  }, [loadAdminData, loadConversations, loadProviders, route])

  useEffect(() => {
    if (!token) {
      return
    }
    void bootstrap(token)
  }, [bootstrap, token])

  async function handleAuthSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoadingAuth(true)
    setAuthError('')
    try {
      const result =
        authMode === 'login'
          ? await api.login(authUsername, authPassword)
          : await api.register(authUsername, authPassword)
      localStorage.setItem('token', result.token)
      setToken(result.token)
      setUser(result.user)
      setAuthPassword('')
      navigateTo('chat', true)
    } catch (error) {
      const message = error instanceof Error ? error.message : '认证失败'
      setAuthError(message === '账号已停用' ? '账号已被管理员停用，请联系管理员处理。' : message)
      void api.authSettings().then(setPublicAuthSettings).catch(() => undefined)
    } finally {
      setLoadingAuth(false)
    }
  }

  function handleLogout(callApi = true) {
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
    setAdminUsers([])
    setConversations([])
    setActiveConversation(null)
    setMessages([])
    setActiveConversationId(null)
    setSelectedProviderId(null)
    setAttachments([])
    setInput('')
    setPendingUserMessage(null)
  }

  async function openConversation(conversationId: number) {
    if (!token) return
    const result = await api.getConversationMessages(token, conversationId)
    shouldFollowStreamRef.current = true
    const summary = conversations.find((item) => item.id === conversationId)
    setActiveConversationId(result.conversation.id)
    setActiveConversation({ ...summary, ...result.conversation })
    setSelectedProviderId(result.conversation.provider_id)
    setMessages(result.messages)
    setPendingUserMessage(null)
    if (route !== 'chat') {
      navigateTo('chat')
    }
  }

  function startNewConversation() {
    shouldFollowStreamRef.current = true
    setActiveConversationId(null)
    setActiveConversation(null)
    setMessages([])
    setInput('')
    setAttachments([])
    setChatError('')
    setStreamingAssistant(null)
    setPendingUserMessage(null)
    if (route !== 'chat') {
      navigateTo('chat')
    }
  }

  function updateFollowStreamState() {
    const root = document.documentElement
    const distanceToBottom = root.scrollHeight - window.scrollY - window.innerHeight
    shouldFollowStreamRef.current = distanceToBottom < 80
  }

  async function sendMessage() {
    if (!token || !selectedProviderId || chatLoading) return
    const currentInput = input
    const currentAttachments = attachments
    const currentConversationId = activeConversationId
    const currentTitle = currentConversation?.title
    const currentCreatedAt = currentConversation?.created_at
    setChatError('')
    setChatLoading(true)
    setStreamingAssistant(null)
    setInput('')
    setAttachments([])
    setPendingUserMessage({
      text: currentInput,
      attachments: currentAttachments,
      createdAt: new Date().toISOString(),
    })
    shouldFollowStreamRef.current = true
    try {
      const body = {
        provider_id: selectedProviderId,
        conversation_id: currentConversationId ?? undefined,
        text: currentInput,
        enable_thinking: selectedProvider?.supports_thinking ? enableThinking : false,
        effort,
        attachments: currentAttachments,
      }

      let finalPayload: { conversation: Conversation; messages: Message[] } | undefined
      await api.streamMessage(token, body, (chunk) => {
        const type = String(chunk.type ?? '')
        if (type === 'conversation') {
          const conversation = chunk.conversation as Partial<Conversation>
          if (conversation?.id) {
            setActiveConversationId(Number(conversation.id))
            setActiveConversation({
              id: Number(conversation.id),
              title: currentTitle ?? (currentInput.trim() ? currentInput.slice(0, 40) : '新对话'),
              provider_id: Number(conversation.provider_id),
              provider_name: String(conversation.provider_name ?? selectedProvider?.name ?? ''),
              model_name: String(conversation.model_name ?? selectedProvider?.model_name ?? ''),
              created_at: currentCreatedAt ?? new Date().toISOString(),
              updated_at: new Date().toISOString(),
            })
          }
          return
        }
        if (type === 'text_delta') {
          setStreamingAssistant((prev) => ({ text: `${prev?.text ?? ''}${String(chunk.delta ?? '')}`, thinking: prev?.thinking ?? '' }))
          return
        }
        if (type === 'thinking_delta') {
          setStreamingAssistant((prev) => ({ text: prev?.text ?? '', thinking: `${prev?.thinking ?? ''}${String(chunk.delta ?? '')}` }))
          return
        }
        if (type === 'done') {
          finalPayload = {
            conversation: chunk.conversation as Conversation,
            messages: chunk.messages as Message[],
          }
          return
        }
        if (type === 'error') {
          throw new Error(String(chunk.detail ?? '流式调用失败'))
        }
      })

      const donePayload = finalPayload
      if (!donePayload) {
        throw new Error('流式响应未正确完成')
      }

      setActiveConversationId(donePayload.conversation.id)
      setActiveConversation(donePayload.conversation)
      setMessages((prev) => (currentConversationId ? [...prev, ...donePayload.messages] : donePayload.messages))
      setPendingUserMessage(null)
      setStreamingAssistant(null)
      await loadConversations(token)
    } catch (error) {
      setPendingUserMessage(null)
      setStreamingAssistant(null)
      setChatError(error instanceof Error ? error.message : '发送失败')
    } finally {
      setChatLoading(false)
    }
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
    setProviderError('')
    setProviderSuccess('')
    try {
      if (editingProviderId) {
        await api.updateProvider(token, editingProviderId, providerForm)
        setProviderSuccess('供应商已更新')
      } else {
        await api.createProvider(token, providerForm)
        setProviderSuccess('供应商已添加')
      }
      setProviderForm(defaultProviderForm)
      setEditingProviderId(null)
      await Promise.all([loadProviders(token), loadAdminData(token, 'admin')])
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : '保存供应商失败')
    }
  }

  async function removeProvider(provider: Provider) {
    if (!token) return
    const confirmed = await openConfirmDialog('删除供应商', `确认删除供应商“${provider.name}”吗？`, '删除')
    if (!confirmed) return
    setProviderError('')
    setProviderSuccess('')
    try {
      await api.deleteProvider(token, provider.id)
      setProviderSuccess('供应商已删除')
      if (selectedProviderId === provider.id) {
        setSelectedProviderId(null)
      }
      await Promise.all([loadProviders(token), loadAdminData(token, 'admin')])
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : '删除供应商失败')
    }
  }

  function editProvider(provider: Provider) {
    setEditingProviderId(provider.id)
    setProviderForm({
      name: provider.name,
      api_url: '',
      api_key: '',
      model_name: provider.model_name,
      supports_thinking: provider.supports_thinking,
      supports_vision: provider.supports_vision,
      thinking_effort: provider.thinking_effort,
      max_context_window: provider.max_context_window,
      max_output_tokens: provider.max_output_tokens,
      is_enabled: provider.is_enabled,
    })
    navigateTo('admin')
  }

  async function submitAdminProfile(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    setAdminProfileMessage('')
    try {
      const updated = await api.updateAdminProfile(token, adminProfile)
      setUser(updated)
      setAdminProfile({ username: updated.username, current_password: '', new_password: '' })
      setAdminProfileMessage('管理员账号已更新')
    } catch (error) {
      setAdminProfileMessage(error instanceof Error ? error.message : '更新管理员失败')
    }
  }

  async function toggleAllowRegistration(value: boolean) {
    if (!token) return
    setUserAdminMessage('')
    setUserAdminError(false)
    try {
      const settings = await api.updateAdminSettings(token, { allow_registration: value })
      setAdminSettings(settings)
      setUserAdminMessage(settings.allow_registration ? '已开启用户注册' : '已关闭用户注册')
    } catch (error) {
      setUserAdminError(true)
      setUserAdminMessage(error instanceof Error ? error.message : '更新注册设置失败')
    }
  }

  async function submitAdminUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    setUserAdminMessage('')
    setUserAdminError(false)
    try {
      const created = await api.createAdminUser(token, userForm)
      setAdminUsers((prev) => [created, ...prev])
      setUserForm({ username: '', password: '', role: 'user', is_enabled: true })
      setUserAdminMessage('用户已创建')
    } catch (error) {
      setUserAdminError(true)
      setUserAdminMessage(error instanceof Error ? error.message : '创建用户失败')
    }
  }

  async function toggleUserEnabled(targetUser: AdminManagedUser) {
    if (!token) return
    setUserAdminMessage('')
    setUserAdminError(false)
    try {
      const updated = await api.updateAdminUser(token, targetUser.id, { is_enabled: !targetUser.is_enabled })
      setAdminUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      if (user?.id === updated.id && !updated.is_enabled) {
        handleLogout(false)
        return
      }
      setUserAdminMessage(updated.is_enabled ? '用户已启用' : '用户已停用')
    } catch (error) {
      setUserAdminError(true)
      setUserAdminMessage(error instanceof Error ? error.message : '更新用户状态失败')
    }
  }

  async function removeAdminUser(targetUser: AdminManagedUser) {
    if (!token) return
    const confirmed = await openConfirmDialog('删除用户', `确认删除用户“${targetUser.username}”吗？这会同时删除其会话记录。`, '删除')
    if (!confirmed) return
    setUserAdminMessage('')
    setUserAdminError(false)
    try {
      await api.deleteAdminUser(token, targetUser.id)
      setAdminUsers((prev) => prev.filter((item) => item.id !== targetUser.id))
      setUserAdminMessage('用户已删除')
    } catch (error) {
      setUserAdminError(true)
      setUserAdminMessage(error instanceof Error ? error.message : '删除用户失败')
    }
  }

  async function resetAdminUserPassword(targetUser: AdminManagedUser) {
    if (!token) return
    const password = (await openPromptDialog('重置用户密码', `输入用户“${targetUser.username}”的新密码`, '', '重置密码'))?.trim()
    if (!password) return
    setUserAdminMessage('')
    setUserAdminError(false)
    try {
      await api.resetAdminUserPassword(token, targetUser.id, { new_password: password })
      setUserAdminMessage('用户密码已重置，原有登录状态已失效')
    } catch (error) {
      setUserAdminError(true)
      setUserAdminMessage(error instanceof Error ? error.message : '重置密码失败')
    }
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
        <div className="auth-shell">
          <div className="auth-card">
          <div className="auth-brand">
            <div className="brand-mark"><Sparkles size={18} /></div>
            <div>
              <h1>deepfake</h1>
              <p>极简聊天界面，多用户与后台配置分离。</p>
            </div>
          </div>
          <div className="auth-tabs">
            <button className={authMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')} type="button">登录</button>
            <button className={authMode === 'register' ? 'active' : ''} disabled={!publicAuthSettings.allow_registration} onClick={() => setAuthMode('register')} type="button">注册</button>
          </div>
          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <label>
              用户名
              <input value={authUsername} onChange={(event) => setAuthUsername(event.target.value)} placeholder="输入用户名" />
            </label>
            <label>
              密码
              <input type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="输入密码" />
            </label>
            {authError ? <div className="error-text">{authError}</div> : null}
            <button className="primary-btn" disabled={loadingAuth} type="submit">
              {loadingAuth ? '处理中...' : authMode === 'login' ? '登录' : '注册并进入'}
            </button>
            {!publicAuthSettings.allow_registration ? <div className="hint-text">当前已关闭普通用户注册</div> : null}
            <div className="hint-text">默认管理员：`admin` / `admin123`</div>
          </form>
          </div>
        </div>
        {dialogState ? renderDialog(dialogState, setDialogState, closeDialog) : null}
      </>
    )
  }

  if (isAdminRoute && user.role === 'admin') {
    return (
      <>
        <div className="admin-page">
        <header className="admin-topbar">
          <div className="admin-topbar-left">
            <div className="brand-mark solid"><Shield size={18} /></div>
            <div>
              <h2>管理员后台</h2>
              <p>单独页面管理供应商、用户注册、账号状态与管理员账号。</p>
            </div>
          </div>
          <div className="admin-topbar-actions">
            <button className="ghost-btn" onClick={() => navigateTo('chat')} type="button">
              <Bot size={16} />
              返回聊天
            </button>
            <button className="ghost-btn" onClick={() => handleLogout()} type="button">
              <LogOut size={16} />
              退出登录
            </button>
          </div>
        </header>

        <main className="admin-main">
          <section className="admin-grid">
            <section className="panel-card">
              <div className="panel-title"><Shield size={16} /> 供应商配置</div>
              <form className="admin-form" onSubmit={submitProvider}>
                <label>
                  供应商名称
                  <input value={providerForm.name} onChange={(event) => setProviderForm((prev) => ({ ...prev, name: event.target.value }))} />
                </label>
                <label>
                  API URL
                  <input value={providerForm.api_url} onChange={(event) => setProviderForm((prev) => ({ ...prev, api_url: event.target.value }))} placeholder={editingProviderId ? '编辑时必须重新填写 API URL' : 'https://.../anthropic/v1'} />
                </label>
                <label>
                  API Key
                  <input type="password" value={providerForm.api_key} onChange={(event) => setProviderForm((prev) => ({ ...prev, api_key: event.target.value }))} placeholder={editingProviderId ? '编辑时必须重新填写 key' : '输入供应商密钥'} />
                </label>
                <label>
                  模型名称
                  <input value={providerForm.model_name} onChange={(event) => setProviderForm((prev) => ({ ...prev, model_name: event.target.value }))} />
                </label>
                <div className="inline-grid">
                  <label>
                    最大上下文
                    <input type="number" value={providerForm.max_context_window} onChange={(event) => setProviderForm((prev) => ({ ...prev, max_context_window: Number(event.target.value) }))} />
                  </label>
                  <label>
                    最大输出
                    <input type="number" value={providerForm.max_output_tokens} onChange={(event) => setProviderForm((prev) => ({ ...prev, max_output_tokens: Number(event.target.value) }))} />
                  </label>
                </div>
                <div className="inline-grid three">
                  <label className="checkbox-row">
                    <input checked={providerForm.supports_thinking} onChange={(event) => setProviderForm((prev) => ({ ...prev, supports_thinking: event.target.checked }))} type="checkbox" />
                    支持思考
                  </label>
                  <label className="checkbox-row">
                    <input checked={providerForm.supports_vision} onChange={(event) => setProviderForm((prev) => ({ ...prev, supports_vision: event.target.checked }))} type="checkbox" />
                    支持视觉
                  </label>
                  <label className="checkbox-row">
                    <input checked={providerForm.is_enabled} onChange={(event) => setProviderForm((prev) => ({ ...prev, is_enabled: event.target.checked }))} type="checkbox" />
                    启用
                  </label>
                </div>
                <label>
                  思考努力等级
                  <select value={providerForm.thinking_effort} onChange={(event) => setProviderForm((prev) => ({ ...prev, thinking_effort: event.target.value }))}>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                    <option value="max">max</option>
                  </select>
                </label>
                {providerError ? <div className="error-text">{providerError}</div> : null}
                {providerSuccess ? <div className="success-text">{providerSuccess}</div> : null}
                <div className="action-row">
                  <button className="primary-btn" type="submit">{editingProviderId ? '更新供应商' : '添加供应商'}</button>
                  {editingProviderId ? (
                    <button className="ghost-btn" onClick={() => { setEditingProviderId(null); setProviderForm(defaultProviderForm) }} type="button">取消编辑</button>
                  ) : null}
                </div>
              </form>
            </section>

            <section className="panel-card">
              <div className="panel-title"><Settings size={16} /> 管理员账号</div>
              <form className="admin-form" onSubmit={submitAdminProfile}>
                <label>
                  管理员用户名
                  <input value={adminProfile.username} onChange={(event) => setAdminProfile((prev) => ({ ...prev, username: event.target.value }))} />
                </label>
                <label>
                  当前密码
                  <input type="password" value={adminProfile.current_password} onChange={(event) => setAdminProfile((prev) => ({ ...prev, current_password: event.target.value }))} />
                </label>
                <label>
                  新密码
                  <input type="password" value={adminProfile.new_password} onChange={(event) => setAdminProfile((prev) => ({ ...prev, new_password: event.target.value }))} />
                </label>
                {adminProfileMessage ? <div className="success-text">{adminProfileMessage}</div> : null}
                <button className="primary-btn" type="submit">更新管理员账号</button>
              </form>
            </section>
          </section>

          <section className="admin-grid user-admin-grid">
            <section className="panel-card">
              <div className="panel-title"><UserRound size={16} /> 用户注册与创建</div>
              <div className="settings-stack">
                <label className="checkbox-row checkbox-card">
                  <input checked={adminSettings.allow_registration} onChange={(event) => void toggleAllowRegistration(event.target.checked)} type="checkbox" />
                  <span>{adminSettings.allow_registration ? '允许普通用户注册' : '关闭普通用户注册'}</span>
                </label>
                <form className="admin-form" onSubmit={submitAdminUser}>
                  <div className="inline-grid">
                    <label>
                      用户名
                      <input value={userForm.username} onChange={(event) => setUserForm((prev) => ({ ...prev, username: event.target.value }))} />
                    </label>
                    <label>
                      初始密码
                      <input type="password" value={userForm.password} onChange={(event) => setUserForm((prev) => ({ ...prev, password: event.target.value }))} />
                    </label>
                  </div>
                  <div className="inline-grid">
                    <label>
                      角色
                      <select value={userForm.role} onChange={(event) => setUserForm((prev) => ({ ...prev, role: event.target.value as 'admin' | 'user' }))}>
                        <option value="user">普通用户</option>
                        <option value="admin">管理员</option>
                      </select>
                    </label>
                    <label className="checkbox-row checkbox-row-inline">
                      <input checked={userForm.is_enabled} onChange={(event) => setUserForm((prev) => ({ ...prev, is_enabled: event.target.checked }))} type="checkbox" />
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
                <input placeholder="搜索用户名" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} />
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
                    {provider.supports_thinking ? <span className="meta-chip">思考</span> : null}
                    {provider.supports_vision ? <span className="meta-chip">视觉</span> : null}
                    <span className="meta-chip">输出 {provider.max_output_tokens}</span>
                    <span className="meta-chip">{provider.is_enabled ? '启用中' : '已禁用'}</span>
                  </div>
                  <div className="provider-actions">
                    <span className="masked-key">{provider.api_key_masked}</span>
                    <button className="ghost-btn" onClick={() => editProvider(provider)} type="button">编辑</button>
                    <button className="ghost-btn danger-text" onClick={() => void removeProvider(provider)} type="button">删除</button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </main>
        </div>
        {dialogState ? renderDialog(dialogState, setDialogState, closeDialog) : null}
      </>
    )
  }

  return (
    <>
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

          <button className={sidebarCollapsed ? 'new-chat-btn icon-only' : 'new-chat-btn'} onClick={startNewConversation} title="开启新对话" type="button">
            <MessageSquarePlus size={16} />
            {sidebarCollapsed ? null : '开启新对话'}
          </button>
        </div>

        <div className={sidebarCollapsed ? 'conversation-list collapsed' : 'conversation-list'}>
          {sidebarCollapsed ? null : <div className="section-title">7 天内</div>}
          {!sidebarCollapsed && conversations.length === 0 ? <div className="empty-tip">还没有会话，发一条消息开始。</div> : null}
          {conversations.map((conversation) => (
            <div key={conversation.id} className={activeConversationId === conversation.id ? 'conversation-item active' : 'conversation-item'}>
              <button className="conversation-main" onClick={() => void openConversation(conversation.id)} type="button">
                <span>{sidebarCollapsed ? conversation.title.slice(0, 1) : conversation.title}</span>
                {sidebarCollapsed ? null : <small>{conversation.provider_name} / {conversation.model_name}</small>}
              </button>
              <div className={sidebarCollapsed ? 'conversation-actions hidden' : 'conversation-actions'}>
                <button aria-label="重命名会话" className="mini-icon-btn" onClick={() => void renameConversation(conversation)} title="重命名会话" type="button">
                  <Pencil size={14} />
                </button>
                <button aria-label="删除会话" className="mini-icon-btn danger" onClick={() => void removeConversation(conversation)} title="删除会话" type="button">
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
                <button className="icon-btn" onClick={() => navigateTo('admin')} title="管理后台" type="button">
                  <LayoutDashboard size={16} />
                </button>
              ) : null}
              <button className="icon-btn" onClick={() => handleLogout()} title="退出登录" type="button">
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
                  {message.thinking_text ? (
                    <details className="thinking-box">
                      <summary><BrainCircuit size={15} /> 已思考</summary>
                      <MarkdownView content={message.thinking_text} />
                    </details>
                  ) : null}
                  <div className={message.role === 'user' ? 'message-bubble user' : 'message-bubble assistant'}>
                    <div className="markdown-body">
                      <MarkdownView content={messagePlainText(message.content)} />
                    </div>
                    <div className="image-grid">
                      {messageImages(message.content).map((image, index) => (
                        <img key={`${message.id}-${index}`} alt="uploaded" src={`data:${image.media_type};base64,${image.data}`} />
                      ))}
                    </div>
                  </div>
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
                    <div className="image-grid">
                      {pendingUserMessage.attachments.map((image, index) => (
                        <img key={`pending-${index}`} alt="uploaded" src={`data:${image.media_type};base64,${image.data}`} />
                      ))}
                    </div>
                  </div>
                </article>
              ) : null}
              {streamingAssistant ? (
                <article className="message-row assistant">
                  <div className="message-meta-row">
                    <span className="message-role">{selectedProvider?.name ?? 'AI'}</span>
                    <time>生成中</time>
                  </div>
                  {streamingAssistant.thinking ? (
                    <details className="thinking-box" open>
                      <summary><BrainCircuit size={15} /> 已思考</summary>
                      <MarkdownView content={streamingAssistant.thinking} />
                    </details>
                  ) : null}
                  <div className="message-bubble assistant stream">
                    <div className="markdown-body">
                      <MarkdownView content={streamingAssistant.text || '...'} />
                    </div>
                  </div>
                </article>
              ) : null}
              <div ref={messageEndRef} />
            </div>
          ) : null}

          <form className={hasVisibleConversation ? 'composer docked compact deepseekish' : 'composer docked center compact deepseekish'} onSubmit={handleSendMessage}>
            <textarea
              placeholder={selectedProvider ? `给 ${selectedProvider.name} 发送消息` : '请先让管理员添加供应商'}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              rows={messages.length === 0 ? 4 : 3}
            />

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
                  <select value={effort} onChange={(event) => setEffort(event.target.value as 'low' | 'medium' | 'high' | 'max')}>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                    <option value="max">max</option>
                  </select>
                ) : null}
                <select className="provider-select inline" value={selectedProviderId ?? ''} onChange={(event) => setSelectedProviderId(Number(event.target.value))}>
                  {providers.map((provider) => (
                    <option key={provider.id} value={provider.id}>{provider.name} / {provider.model_name}</option>
                  ))}
                </select>
              </div>

              <div className="right-tools">
                {selectedProvider?.supports_vision ? (
                  <button className="upload-btn" onClick={() => fileInputRef.current?.click()} type="button">
                    <Eye size={17} />
                  </button>
                ) : null}
                <button className="send-btn" disabled={chatLoading || !selectedProviderId} type="submit">
                  <SendHorizonal size={17} />
                </button>
              </div>
            </div>

            <input accept="image/jpeg,image/png,image/gif,image/webp" hidden multiple onChange={handleFileChange} ref={fileInputRef} type="file" />
            {chatLoading ? <div className="loading-text">模型正在生成回复...</div> : null}
            {chatError ? <div className="error-text">{chatError}</div> : null}
          </form>
        </div>
      </main>
      </div>
      {dialogState ? renderDialog(dialogState, setDialogState, closeDialog) : null}
    </>
  )
}

function renderDialog(
  dialogState: DialogState,
  setDialogState: Dispatch<SetStateAction<DialogState | null>>,
  closeDialog: (value: boolean | string | null) => void,
) {
  return (
    <div className="modal-backdrop" onClick={() => closeDialog(null)} role="presentation">
      <div aria-modal="true" className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <h3>{dialogState.title}</h3>
          <p>{dialogState.message}</p>
        </div>
        {dialogState.mode === 'prompt' ? (
          <input
            autoFocus
            className="modal-input"
            onChange={(event) => setDialogState((current) => (current ? { ...current, value: event.target.value } : current))}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                closeDialog(dialogState.value)
              }
            }}
            value={dialogState.value}
          />
        ) : null}
        <div className="modal-actions">
          <button className="ghost-btn" onClick={() => closeDialog(null)} type="button">
            {dialogState.cancelLabel}
          </button>
          <button
            className={dialogState.confirmLabel === '删除' ? 'primary-btn danger-fill' : 'primary-btn'}
            onClick={() => closeDialog(dialogState.mode === 'prompt' ? dialogState.value : true)}
            type="button"
          >
            {dialogState.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

export default App
