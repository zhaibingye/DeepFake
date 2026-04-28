import { useState } from 'react'

import type { ChatStreamEvent, TimelinePart } from '../../types'
import { applyTimelineEvent, type TimelineState } from './timeline'

const LEGACY_THINKING_ID = 'legacy-thinking'
const LEGACY_ANSWER_ID = 'legacy-answer'

function timelineRevision(parts: TimelinePart[]) {
  return parts
    .map((part) =>
      [
        part.id,
        part.status,
        part.label ?? '',
        part.detail ?? '',
        part.text ?? '',
        part.output ?? '',
        part.input ?? '',
      ].join(':'),
    )
    .join('|')
}

export function defaultExpandedById(parts: TimelinePart[]) {
  const latestAnswer = [...parts].reverse().find((part) => part.kind === 'answer')
  const fallbackPartId = latestAnswer?.id ?? parts.at(-1)?.id

  return Object.fromEntries(
    parts.map((part) => [part.id, part.status === 'error' || part.id === fallbackPartId]),
  ) as Record<string, boolean>
}

function startTimelinePart(state: TimelineState, part: TimelinePart): TimelineState {
  const nextState = applyTimelineEvent(state, { type: 'timeline_part_start', part })
  const nextExpandedById = Object.fromEntries(
    state.parts.map((existingPart) => {
      const nextPart = nextState.parts.find((candidate) => candidate.id === existingPart.id) ?? existingPart
      return [existingPart.id, Boolean(state.manuallyExpanded[existingPart.id] || nextPart.status === 'error')]
    }),
  ) as Record<string, boolean>

  return {
    ...nextState,
    expandedById: { ...nextExpandedById, [part.id]: true },
  }
}

function ensurePartStarted(state: TimelineState, part: TimelinePart): TimelineState {
  if (state.parts.some((existingPart) => existingPart.id === part.id)) {
    return state
  }

  return startTimelinePart(state, part)
}

function appendTextDelta(state: TimelineState, partId: string, part: TimelinePart, delta: string): TimelineState {
  if (!delta) {
    return state
  }

  const nextState = ensurePartStarted(state, part)

  return applyTimelineEvent(nextState, {
    type: 'timeline_part_delta',
    part_id: partId,
    delta: { text: delta },
  })
}

export function createTimelineState(initialParts: TimelinePart[] = []): TimelineState {
  return {
    parts: initialParts,
    expandedById: defaultExpandedById(initialParts),
    manuallyExpanded: {},
  }
}

export function reduceTimelineState(state: TimelineState, event: ChatStreamEvent): TimelineState {
  if (event.type === 'timeline_part_start') {
    return startTimelinePart(state, event.part)
  }

  if (
    event.type === 'timeline_part_delta' ||
    event.type === 'timeline_part_end' ||
    event.type === 'timeline_part_error'
  ) {
    return applyTimelineEvent(state, event)
  }

  if (event.type === 'thinking_delta') {
    return appendTextDelta(
      state,
      LEGACY_THINKING_ID,
      { id: LEGACY_THINKING_ID, kind: 'thinking', status: 'running', text: '' },
      event.delta,
    )
  }

  if (event.type === 'text_delta') {
    return appendTextDelta(
      state,
      LEGACY_ANSWER_ID,
      { id: LEGACY_ANSWER_ID, kind: 'answer', status: 'running', text: '' },
      event.delta,
    )
  }

  if (event.type === 'activity') {
    if (event.activity.kind === 'thinking' && !state.parts.some((part) => part.id === LEGACY_THINKING_ID)) {
      return state
    }

    const partId = event.activity.kind === 'thinking' ? LEGACY_THINKING_ID : event.activity.id
    const nextState = ensurePartStarted(state, {
      id: partId,
      kind: event.activity.kind,
      status: event.activity.status,
      label: event.activity.label,
      detail: event.activity.detail,
      output: event.activity.output,
      text: event.activity.kind === 'thinking' ? '' : undefined,
    })
    const withDelta = applyTimelineEvent(nextState, {
      type: 'timeline_part_delta',
      part_id: partId,
      delta: {
        status: event.activity.status,
        label: event.activity.label,
        detail: event.activity.detail,
        output: event.activity.output,
      },
    })

    if (event.activity.status !== 'error') {
      return withDelta
    }

    return applyTimelineEvent(withDelta, {
      type: 'timeline_part_error',
      part_id: partId,
      detail: event.activity.detail || `${event.activity.label} 失败`,
    })
  }

  return state
}

export function useTimelineState(initialParts: TimelinePart[] = []) {
  const [state, setState] = useState(() => ({
    ...createTimelineState(initialParts),
    revision: 0,
  }))

  function dispatchTimelineEvent(event: ChatStreamEvent) {
    setState((prev) => ({
      ...reduceTimelineState(prev, event),
      revision: prev.revision + 1,
    }))
  }

  function setExpanded(partId: string, nextExpanded: boolean) {
    setState((prev) => {
      const manuallyExpanded = { ...prev.manuallyExpanded }

      if (nextExpanded) {
        manuallyExpanded[partId] = true
      } else {
        delete manuallyExpanded[partId]
      }

      return {
        ...prev,
        expandedById: { ...prev.expandedById, [partId]: nextExpanded },
        manuallyExpanded,
      }
    })
  }

  function reset(nextParts: TimelinePart[] = []) {
    setState((prev) => ({
      ...createTimelineState(nextParts),
      revision: prev.revision + 1,
    }))
  }

  return {
    ...state,
    dispatchTimelineEvent,
    setExpanded,
    reset,
    revision: timelineRevision(state.parts),
  }
}
