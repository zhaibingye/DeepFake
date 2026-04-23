import { useState } from 'react'

import type { TimelinePart } from '../../types'
import { AnswerBlock } from './AnswerBlock'
import { ThinkingBlock } from './ThinkingBlock'
import { ToolBlock } from './ToolBlock'
import { defaultExpandedById } from './useTimelineState'

export function TimelineList({
  parts,
  expandedById,
  onToggle,
}: {
  parts: TimelinePart[]
  expandedById?: Record<string, boolean>
  onToggle?: (partId: string, nextOpen: boolean) => void
}) {
  const [internalExpandedById, setInternalExpandedById] = useState<Record<string, boolean>>(() =>
    defaultExpandedById(parts),
  )

  const resolvedExpandedById = expandedById ?? internalExpandedById

  function handleToggle(partId: string, nextOpen: boolean) {
    if (onToggle) {
      onToggle(partId, nextOpen)
      return
    }

    setInternalExpandedById((prev) => ({ ...prev, [partId]: nextOpen }))
  }

  return (
    <div className="timeline-list">
      {parts.map((part) => {
        const sharedProps = {
          part,
          open: Boolean(resolvedExpandedById[part.id]),
          onToggle: (nextOpen: boolean) => handleToggle(part.id, nextOpen),
        }

        if (part.kind === 'thinking') {
          return <ThinkingBlock key={part.id} {...sharedProps} />
        }

        if (part.kind === 'tool') {
          return <ToolBlock key={part.id} {...sharedProps} />
        }

        return <AnswerBlock key={part.id} {...sharedProps} />
      })}
    </div>
  )
}
