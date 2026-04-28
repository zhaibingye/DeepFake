import type { Dispatch, MutableRefObject, SetStateAction } from 'react'

import { api } from '../../api'
import { constrainProviderState } from '../../appState'
import type {
  Attachment,
  ChatDonePayload,
  ChatRequest,
  ChatStreamEvent,
  Conversation,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
  SearchProviderStatus,
  TimelinePart,
  ThinkingEffort,
} from '../../types'
import type { SearchProviderLoadState } from './searchProviders'
import { getSearchProviderUnavailableReason } from './searchProviders'

type TimelineController = {
  dispatchTimelineEvent: (event: ChatStreamEvent) => void
  reset: () => void
}

type ConversationSetters = {
  setConversations: Dispatch<SetStateAction<Conversation[]>>
  setActiveConversation: Dispatch<SetStateAction<Conversation | null>>
}

type ComposerState = {
  effort: ThinkingEffort
  enableThinking: boolean
  enableSearch: boolean
  attachments: Attachment[]
}

type ApplyProviderSelection = (nextProviderId: number | null, providerList?: Provider[]) => void

function syncConversationState(
  list: Conversation[],
  { setConversations, setActiveConversation }: ConversationSetters,
) {
  setConversations(list)
  setActiveConversation((prev) => {
    if (!prev) return prev
    return list.find((item) => item.id === prev.id) ?? prev
  })
}

export async function loadProvidersState(options: {
  token: string
  providersRef: MutableRefObject<Provider[]>
  selectedProviderIdRef: MutableRefObject<number | null>
  setProviders: Dispatch<SetStateAction<Provider[]>>
  applyProviderSelection: ApplyProviderSelection
}) {
  const list = await api.listProviders(options.token)
  options.providersRef.current = list
  options.setProviders(list)
  const nextProviderId =
    options.selectedProviderIdRef.current &&
    list.some((provider) => provider.id === options.selectedProviderIdRef.current)
      ? options.selectedProviderIdRef.current
      : list[0]?.id ?? null
  options.applyProviderSelection(nextProviderId, list)
}

export async function loadSearchProvidersState(options: {
  setSearchProviderLoadState: Dispatch<SetStateAction<SearchProviderLoadState>>
  setSearchProviders: Dispatch<SetStateAction<SearchProviderAvailability | null>>
}) {
  options.setSearchProviderLoadState('loading')
  try {
    const nextSearchProviders = await api.listSearchProviders()
    options.setSearchProviders(nextSearchProviders)
    options.setSearchProviderLoadState('ready')
  } catch (error) {
    options.setSearchProviders(null)
    options.setSearchProviderLoadState('error')
    throw error
  }
}

export async function loadConversationsState(
  token: string,
  setters: ConversationSetters,
) {
  const list = await api.listConversations(token)
  syncConversationState(list, setters)
}

export async function loadConversationsForSessionState(options: {
  token: string
  sessionVersion: number
  authSessionVersionRef: MutableRefObject<number>
  setConversations: Dispatch<SetStateAction<Conversation[]>>
  setActiveConversation: Dispatch<SetStateAction<Conversation | null>>
}) {
  const list = await api.listConversations(options.token)
  if (options.sessionVersion !== options.authSessionVersionRef.current) {
    return false
  }
  syncConversationState(list, options)
  return true
}

export async function openConversationState(options: {
  token: string
  conversationId: number
  chatLoading: boolean
  conversations: Conversation[]
  shouldFollowStreamRef: MutableRefObject<boolean>
  setActiveConversationId: Dispatch<SetStateAction<number | null>>
  setActiveConversation: Dispatch<SetStateAction<Conversation | null>>
  applyProviderSelection: ApplyProviderSelection
  setMessages: Dispatch<SetStateAction<ChatDonePayload['messages']>>
  streamingTimeline: TimelineController
  setPendingUserMessage: Dispatch<
    SetStateAction<{ text: string; attachments: Attachment[]; createdAt: string } | null>
  >
  route: 'chat' | 'admin'
  navigateTo: (route: 'chat' | 'admin') => void
}) {
  if (options.chatLoading) return

  const result = await api.getConversationMessages(options.token, options.conversationId)
  options.shouldFollowStreamRef.current = true
  const summary = options.conversations.find((item) => item.id === options.conversationId)
  options.setActiveConversationId(result.conversation.id)
  options.setActiveConversation({ ...summary, ...result.conversation })
  options.applyProviderSelection(result.conversation.provider_id)
  options.setMessages(result.messages)
  options.streamingTimeline.reset()
  options.setPendingUserMessage(null)
  if (options.route !== 'chat') {
    options.navigateTo('chat')
  }
}

export function startNewConversationState(options: {
  chatLoading: boolean
  shouldFollowStreamRef: MutableRefObject<boolean>
  setActiveConversationId: Dispatch<SetStateAction<number | null>>
  setActiveConversation: Dispatch<SetStateAction<Conversation | null>>
  setMessages: Dispatch<SetStateAction<ChatDonePayload['messages']>>
  setInput: Dispatch<SetStateAction<string>>
  setAttachments: Dispatch<SetStateAction<Attachment[]>>
  setChatError: Dispatch<SetStateAction<string>>
  streamingTimeline: TimelineController
  setPendingUserMessage: Dispatch<
    SetStateAction<{ text: string; attachments: Attachment[]; createdAt: string } | null>
  >
  route: 'chat' | 'admin'
  navigateTo: (route: 'chat' | 'admin') => void
}) {
  if (options.chatLoading) return
  options.shouldFollowStreamRef.current = true
  options.setActiveConversationId(null)
  options.setActiveConversation(null)
  options.setMessages([])
  options.setInput('')
  options.setAttachments([])
  options.setChatError('')
  options.streamingTimeline.reset()
  options.setPendingUserMessage(null)
  if (options.route !== 'chat') {
    options.navigateTo('chat')
  }
}

export function handleChatStreamChunk(
  chunk: ChatStreamEvent,
  handlers: {
    onConversation: (conversation: Partial<Conversation> & Pick<Conversation, 'id' | 'provider_id'>) => void
    onTimelineEvent: (event: Extract<
      ChatStreamEvent,
      | { type: 'timeline_part_start'; part: TimelinePart }
      | { type: 'timeline_part_delta'; part_id: string; delta: Partial<TimelinePart> }
      | { type: 'timeline_part_end'; part_id: string }
      | { type: 'timeline_part_error'; part_id: string; detail: string }
    >) => void
    onDone: (payload: ChatDonePayload) => void
  },
) {
  if (chunk.type === 'conversation') {
    handlers.onConversation(chunk.conversation)
    return
  }
  if (
    chunk.type === 'timeline_part_start' ||
    chunk.type === 'timeline_part_delta' ||
    chunk.type === 'timeline_part_end' ||
    chunk.type === 'timeline_part_error'
  ) {
    handlers.onTimelineEvent(chunk)
    return
  }
  if (chunk.type === 'done') {
    handlers.onDone({
      conversation: chunk.conversation,
      messages: chunk.messages,
    })
    return
  }
  if (chunk.type === 'error') {
    throw new Error(chunk.detail || '流式调用失败')
  }
}

export async function sendMessageState(options: {
  token: string
  selectedProviderId: number | null
  chatLoading: boolean
  authSessionVersionRef: MutableRefObject<number>
  enableSearch: boolean
  selectedProviderSupportsToolCalling: boolean
  searchProvider: SearchProviderKind
  selectedSearchProviderStatus: SearchProviderStatus | null
  searchProviderLoadState: SearchProviderLoadState
  setChatError: Dispatch<SetStateAction<string>>
  input: string
  attachments: Attachment[]
  activeConversationId: number | null
  activeConversation: Conversation | null
  messages: ChatDonePayload['messages']
  setChatLoading: Dispatch<SetStateAction<boolean>>
  streamingTimeline: TimelineController
  setInput: Dispatch<SetStateAction<string>>
  setAttachments: Dispatch<SetStateAction<Attachment[]>>
  setPendingUserMessage: Dispatch<
    SetStateAction<{ text: string; attachments: Attachment[]; createdAt: string } | null>
  >
  shouldFollowStreamRef: MutableRefObject<boolean>
  streamAbortRef: MutableRefObject<AbortController | null>
  selectedProvider: Provider | null
  enableThinking: boolean
  effort: ThinkingEffort
  setActiveConversationId: Dispatch<SetStateAction<number | null>>
  setActiveConversation: Dispatch<SetStateAction<Conversation | null>>
  setMessages: Dispatch<SetStateAction<ChatDonePayload['messages']>>
  loadConversationsForSession: (currentToken: string, sessionVersion: number) => Promise<boolean>
}) {
  if (!options.selectedProviderId || options.chatLoading) return

  const sessionVersion = options.authSessionVersionRef.current
  if (options.enableSearch && !options.selectedProviderSupportsToolCalling) {
    options.setChatError('当前模型不支持原生工具调用，无法开启联网搜索')
    return
  }
  if (options.enableSearch) {
    const unavailableReason = getSearchProviderUnavailableReason(
      options.searchProvider,
      options.selectedSearchProviderStatus,
      options.searchProviderLoadState,
    )
    if (unavailableReason) {
      options.setChatError(unavailableReason)
      return
    }
  }

  const currentInput = options.input
  const currentAttachments = options.attachments
  const currentConversationId = options.activeConversationId
  const previousConversation = options.activeConversation
  const previousMessages = options.messages
  const currentTitle = options.activeConversation?.title
  const currentCreatedAt = options.activeConversation?.created_at
  let streamedConversationId: number | null = null

  options.setChatError('')
  options.setChatLoading(true)
  options.streamingTimeline.reset()
  options.setInput('')
  options.setAttachments([])
  options.setPendingUserMessage({
    text: currentInput,
    attachments: currentAttachments,
    createdAt: new Date().toISOString(),
  })
  options.shouldFollowStreamRef.current = true

  try {
    const abortController = new AbortController()
    options.streamAbortRef.current = abortController
    const body: ChatRequest = {
      provider_id: options.selectedProviderId,
      conversation_id: currentConversationId ?? undefined,
      text: currentInput,
      enable_thinking: options.selectedProvider?.supports_thinking ? options.enableThinking : false,
      enable_search: options.selectedProviderSupportsToolCalling ? options.enableSearch : false,
      search_provider:
        options.selectedProviderSupportsToolCalling && options.enableSearch
          ? options.searchProvider
          : null,
      effort: options.effort,
      attachments: currentAttachments,
    }

    let finalPayload: ChatDonePayload | undefined
    await api.streamMessage(
      options.token,
      body,
      (chunk) => {
        if (sessionVersion !== options.authSessionVersionRef.current) {
          return
        }

        handleChatStreamChunk(chunk, {
          onConversation: (conversation) => {
            streamedConversationId = Number(conversation.id)
            options.setActiveConversationId(Number(conversation.id))
            options.setActiveConversation({
              id: Number(conversation.id),
              title: currentTitle ?? (currentInput.trim() ? currentInput.slice(0, 40) : '新对话'),
              provider_id: Number(conversation.provider_id),
              provider_name: String(conversation.provider_name ?? options.selectedProvider?.name ?? ''),
              model_name: String(conversation.model_name ?? options.selectedProvider?.model_name ?? ''),
              created_at: currentCreatedAt ?? new Date().toISOString(),
              updated_at: new Date().toISOString(),
            })
          },
          onTimelineEvent: (event) => {
            options.streamingTimeline.dispatchTimelineEvent(event)
          },
          onDone: (payload) => {
            finalPayload = payload
          },
        })
      },
      abortController.signal,
    )

    const donePayload = finalPayload
    if (sessionVersion !== options.authSessionVersionRef.current) {
      return
    }
    if (!donePayload) {
      throw new Error('流式响应未正确完成')
    }

    options.setActiveConversationId(donePayload.conversation.id)
    options.setActiveConversation(donePayload.conversation)
    options.setMessages((prev) =>
      currentConversationId ? [...prev, ...donePayload.messages] : donePayload.messages,
    )
    options.setPendingUserMessage(null)
    options.streamingTimeline.reset()
    await options.loadConversationsForSession(options.token, sessionVersion)
  } catch (error) {
    if (sessionVersion !== options.authSessionVersionRef.current) {
      return
    }
    options.setActiveConversationId(currentConversationId)
    options.setActiveConversation(previousConversation)
    options.setMessages(previousMessages)
    options.setPendingUserMessage(null)
    options.streamingTimeline.reset()
    const aborted =
      error instanceof DOMException
        ? error.name === 'AbortError'
        : error instanceof Error && error.name === 'AbortError'
    const conversationToSync = streamedConversationId ?? currentConversationId
    if (conversationToSync) {
      try {
        const result = await api.getConversationMessages(options.token, conversationToSync)
        if (sessionVersion !== options.authSessionVersionRef.current) {
          return
        }
        options.setActiveConversationId(result.conversation.id)
        options.setActiveConversation(result.conversation)
        options.setMessages(result.messages)
      } catch {
        options.setActiveConversationId(currentConversationId)
        options.setActiveConversation(previousConversation)
        options.setMessages(previousMessages)
      }
    } else {
      options.setActiveConversationId(null)
      options.setActiveConversation(null)
      options.setMessages([])
    }
    await options.loadConversationsForSession(options.token, sessionVersion).catch(() => undefined)
    if (sessionVersion !== options.authSessionVersionRef.current) {
      return
    }
    if (aborted) {
      options.setChatError('')
      return
    }
    options.setChatError(error instanceof Error ? error.message : '发送失败')
  } finally {
    if (sessionVersion === options.authSessionVersionRef.current) {
      options.streamAbortRef.current = null
      options.setChatLoading(false)
    }
  }
}

export function applyProviderSelectionState(options: {
  nextProviderId: number | null
  providerList: Provider[]
  composerState: ComposerState
  setSelectedProviderId: Dispatch<SetStateAction<number | null>>
  setEffort: Dispatch<SetStateAction<ThinkingEffort>>
  setEnableThinking: Dispatch<SetStateAction<boolean>>
  setEnableSearch: Dispatch<SetStateAction<boolean>>
  setAttachments: Dispatch<SetStateAction<Attachment[]>>
  selectedProviderIdRef: MutableRefObject<number | null>
  composerStateRef: MutableRefObject<ComposerState>
}) {
  options.setSelectedProviderId(options.nextProviderId)
  options.selectedProviderIdRef.current = options.nextProviderId

  const nextProvider =
    options.providerList.find((provider) => provider.id === options.nextProviderId) ?? null
  const nextState = constrainProviderState(options.composerState, nextProvider)

  if (nextState.effort !== options.composerState.effort) {
    options.setEffort(nextState.effort)
  }
  if (nextState.enableThinking !== options.composerState.enableThinking) {
    options.setEnableThinking(nextState.enableThinking)
  }
  if (nextState.enableSearch !== options.composerState.enableSearch) {
    options.setEnableSearch(nextState.enableSearch)
  }
  if (nextState.attachments !== options.composerState.attachments) {
    options.setAttachments(nextState.attachments)
  }
  options.composerStateRef.current = nextState
}
