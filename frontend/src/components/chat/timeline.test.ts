import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { applyTimelineEvent, toRenderableTimeline } from './timeline'
import type { TimelineState } from './timeline'
import { TimelineList } from './TimelineList'
import { reduceTimelineState } from './useTimelineState.ts'
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

  it('marks the current block expanded and previous auto-collapsed', () => {
    let state: TimelineState = { parts: [], expandedById: {}, manuallyExpanded: {} }

    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: { id: 'thinking-1', kind: 'thinking', status: 'running', text: '' },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: { id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' },
    })

    expect(state.expandedById['thinking-1']).toBe(false)
    expect(state.expandedById['tool-1']).toBe(true)
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
    state = reduceTimelineState(state, {
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

  it('renders historical answer parts as assistant message bubbles', () => {
    const markup = renderToStaticMarkup(
      createElement(TimelineList, {
        parts: [
          { id: 'thinking-1', kind: 'thinking', status: 'done', text: '先分析' },
          { id: 'answer-1', kind: 'answer', status: 'done', text: '最终回答' },
        ],
      }),
    )

    expect(markup).toContain('class="message-bubble assistant"')
    expect(markup).toContain('最终回答')
    expect(markup).not.toMatch(/<details[^>]*class="timeline-block thinking done"[^>]*open=""[^>]*>/)
  })

  it('keeps the answer block expanded when it starts after a tool block', () => {
    let state: TimelineState = { parts: [], expandedById: {}, manuallyExpanded: {} }

    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: { id: 'tool-1', kind: 'tool', status: 'running', label: 'Exa 搜索' },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: { id: 'answer-1', kind: 'answer', status: 'running', text: '' },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_end',
      part_id: 'answer-1',
    })

    expect(state.expandedById['tool-1']).toBe(false)
    expect(state.expandedById['answer-1']).toBe(true)
  })

  it('applies timeline streaming events into ordered parts', () => {
    let state: TimelineState = { parts: [], expandedById: {}, manuallyExpanded: {} }

    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: {
        id: 'thinking-1',
        kind: 'thinking',
        status: 'running',
        text: '',
      },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_delta',
      part_id: 'thinking-1',
      delta: {
        text: '先分析',
      },
    })
    state = reduceTimelineState(state, { type: 'timeline_part_end', part_id: 'thinking-1' })
    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: {
        id: 'tool-1',
        kind: 'tool',
        status: 'running',
        label: 'Exa 搜索',
      },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_delta',
      part_id: 'tool-1',
      delta: {
        status: 'done',
        output: '命中结果',
      },
    })
    state = reduceTimelineState(state, { type: 'timeline_part_end', part_id: 'tool-1' })
    state = reduceTimelineState(state, {
      type: 'timeline_part_start',
      part: {
        id: 'answer-1',
        kind: 'answer',
        status: 'running',
        text: '',
      },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_delta',
      part_id: 'answer-1',
      delta: {
        text: '最终回答',
      },
    })

    expect(state.parts).toEqual([
      { id: 'thinking-1', kind: 'thinking', status: 'done', text: '先分析' },
      { id: 'tool-1', kind: 'tool', status: 'done', label: 'Exa 搜索', output: '命中结果' },
      { id: 'answer-1', kind: 'answer', status: 'running', text: '最终回答' },
    ])
    expect(state.expandedById['thinking-1']).toBe(false)
    expect(state.expandedById['tool-1']).toBe(false)
    expect(state.expandedById['answer-1']).toBe(true)
  })

  it('appends streamed text deltas instead of replacing previous text', () => {
    let state: TimelineState = {
      parts: [{ id: 'answer-1', kind: 'answer', status: 'running', text: '' }],
      expandedById: { 'answer-1': true },
      manuallyExpanded: {},
    }

    state = reduceTimelineState(state, {
      type: 'timeline_part_delta',
      part_id: 'answer-1',
      delta: { text: '第一段' },
    })
    state = reduceTimelineState(state, {
      type: 'timeline_part_delta',
      part_id: 'answer-1',
      delta: { text: '，第二段' },
    })

    expect(state.parts.find((part) => part.id === 'answer-1')?.text).toBe('第一段，第二段')
  })

  it('keeps legacy text delta compatibility with append semantics', () => {
    let state: TimelineState = { parts: [], expandedById: {}, manuallyExpanded: {} }

    state = reduceTimelineState(state, { type: 'text_delta', delta: '旧' })
    state = reduceTimelineState(state, { type: 'text_delta', delta: '流式' })

    expect(state.parts.find((part) => part.id === 'legacy-answer')?.text).toBe('旧流式')
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
