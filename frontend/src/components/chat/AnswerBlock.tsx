import { MessageSquare } from 'lucide-react'

import { MarkdownView } from '../MarkdownView'
import type { TimelinePart } from '../../types'
import { TimelineBlock } from './TimelineBlock'

export function AnswerBlock({
  part,
  open,
  onToggle,
}: {
  part: TimelinePart
  open: boolean
  onToggle: (nextOpen: boolean) => void
}) {
  const title = part.label || (part.status === 'running' ? '正在回答' : '最终回答')
  const meta = part.detail || (part.status === 'running' ? '答案仍在生成' : undefined)

  return (
    <TimelineBlock
      part={part}
      title={title}
      meta={meta}
      icon={<MessageSquare size={14} />}
      open={open}
      onToggle={onToggle}
    >
      <div className="timeline-markdown">
        <MarkdownView content={part.text || '...'} />
      </div>
    </TimelineBlock>
  )
}
