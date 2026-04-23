import { describe, expect, it } from 'vitest'

import { applyTimelineEvent, toRenderableTimeline } from './timeline'
import type { TimelineState } from './timeline'
import { messagePlainText } from '../../utils'

describe('timeline helpers', () => {
  it('appends parts in stream order', () => {
    let state: TimelineState = { parts: [], expandedById: {}, manuallyExpanded: {} }

    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
    })
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' },
    })

    expect(state.parts.map((part) => part.id)).toEqual(['thinking-1', 'tool-1'])
  })

  it('keeps manual expansion after a part ends', () => {
    let state: TimelineState = {
      parts: [{ id: 'thinking-1', kind: 'thinking', status: 'running', text: '' }],
      expandedById: { 'thinking-1': true },
      manuallyExpanded: { 'thinking-1': true },
    }

    state = applyTimelineEvent(state, { type: 'timeline_part_end', part_id: 'thinking-1' })

    expect(state.expandedById['thinking-1']).toBe(true)
  })

  it('keeps error-expanded parts open when later parts start', () => {
    let state: TimelineState = {
      parts: [{ id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' }],
      expandedById: { 'tool-1': true },
      manuallyExpanded: {},
    }

    state = applyTimelineEvent(state, {
      type: 'timeline_part_error',
      part_id: 'tool-1',
      detail: '搜索失败',
    })
    state = applyTimelineEvent(state, {
      type: 'timeline_part_start',
      part: { id: 'answer-1', kind: 'answer', status: 'running', text: '' },
    })

    expect(state.expandedById['tool-1']).toBe(true)
    expect(state.expandedById['answer-1']).toBe(true)
  })

  it('maps legacy assistant messages into thinking and answer parts', () => {
    const message = {
      id: 1,
      role: 'assistant' as const,
      content: '旧回答',
      thinking_text: '旧思考',
      created_at: '2026-04-22T00:00:00Z',
    }

    expect(toRenderableTimeline(message).map((part) => part.kind)).toEqual(['thinking', 'answer'])
  })

  it('extracts answer text from timeline parts content', () => {
    expect(
      messagePlainText({
        parts: [
          { id: 'thinking-1', kind: 'thinking', status: 'done', text: '先分析' },
          { id: 'answer-1', kind: 'answer', status: 'done', text: '最终回答' },
        ],
      }),
    ).toBe('最终回答')
  })
})
