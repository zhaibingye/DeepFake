import { describe, expect, it, vi } from 'vitest'

import { handleChatStreamChunk } from './controller'

describe('chat stream controller', () => {
  it('routes timeline events through the dedicated handler', () => {
    const onConversation = vi.fn()
    const onTimelineEvent = vi.fn()
    const onDone = vi.fn()

    handleChatStreamChunk(
      {
        type: 'timeline_part_start',
        part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
      },
      { onConversation, onTimelineEvent, onDone },
    )

    expect(onConversation).not.toHaveBeenCalled()
    expect(onDone).not.toHaveBeenCalled()
    expect(onTimelineEvent).toHaveBeenCalledWith({
      type: 'timeline_part_start',
      part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
    })
  })

  it('captures final done payloads without mixing them into timeline dispatch', () => {
    const onConversation = vi.fn()
    const onTimelineEvent = vi.fn()
    const onDone = vi.fn()

    handleChatStreamChunk(
      {
        type: 'done',
        conversation: {
          id: 1,
          title: 'test',
          provider_id: 2,
          created_at: '2026-04-23T00:00:00Z',
          updated_at: '2026-04-23T00:00:00Z',
        },
        messages: [],
      },
      { onConversation, onTimelineEvent, onDone },
    )

    expect(onConversation).not.toHaveBeenCalled()
    expect(onTimelineEvent).not.toHaveBeenCalled()
    expect(onDone).toHaveBeenCalledWith({
      conversation: {
        id: 1,
        title: 'test',
        provider_id: 2,
        created_at: '2026-04-23T00:00:00Z',
        updated_at: '2026-04-23T00:00:00Z',
      },
      messages: [],
    })
  })

  it('throws stream errors so callers can rollback optimistic state', () => {
    expect(() =>
      handleChatStreamChunk(
        {
          type: 'error',
          detail: 'provider failed',
        },
        {
          onConversation: vi.fn(),
          onTimelineEvent: vi.fn(),
          onDone: vi.fn(),
        },
      ),
    ).toThrowError('provider failed')
  })
})
