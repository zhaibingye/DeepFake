import type { ChatStreamEvent, Message, TimelinePart } from '../../types'

export type TimelineState = {
  parts: TimelinePart[]
  expandedById: Record<string, boolean>
  manuallyExpanded: Record<string, boolean>
}

export function toRenderableTimeline(message: Message): TimelinePart[] {
  if (Array.isArray(message.parts) && message.parts.length > 0) {
    return message.parts
  }

  if (
    typeof message.content === 'object' &&
    message.content !== null &&
    !Array.isArray(message.content) &&
    Array.isArray(message.content.parts)
  ) {
    return message.content.parts
  }

  const parts: TimelinePart[] = []

  if (message.thinking_text) {
    parts.push({
      id: `legacy-thinking-${message.id}`,
      kind: 'thinking',
      status: 'done',
      text: message.thinking_text,
    })
  }

  if (typeof message.content === 'string' && message.content) {
    parts.push({
      id: `legacy-answer-${message.id}`,
      kind: 'answer',
      status: 'done',
      text: message.content,
    })
  }

  return parts
}

export function applyTimelineEvent(state: TimelineState, event: ChatStreamEvent): TimelineState {
  if (event.type === 'timeline_part_start') {
    const nextExpandedById = Object.fromEntries(
      state.parts.map((part) => [
        part.id,
        Boolean(state.manuallyExpanded[part.id] || state.expandedById[part.id]),
      ]),
    ) as Record<string, boolean>

    return {
      parts: [...state.parts, event.part],
      expandedById: { ...nextExpandedById, [event.part.id]: true },
      manuallyExpanded: state.manuallyExpanded,
    }
  }

  if (event.type === 'timeline_part_delta') {
    return {
      ...state,
      parts: state.parts.map((part) => {
        if (part.id !== event.part_id) return part
        const nextPart = { ...part, ...event.delta }
        if (typeof event.delta.text === 'string') {
          nextPart.text = `${part.text ?? ''}${event.delta.text}`
        }
        return nextPart
      }),
    }
  }

  if (event.type === 'timeline_part_end') {
    return {
      ...state,
      parts: state.parts.map((part) => (part.id === event.part_id ? { ...part, status: 'done' } : part)),
    }
  }

  if (event.type === 'timeline_part_error') {
    return {
      ...state,
      parts: state.parts.map((part) =>
        part.id === event.part_id ? { ...part, status: 'error', detail: event.detail } : part,
      ),
      expandedById: { ...state.expandedById, [event.part_id]: true },
    }
  }

  return state
}
