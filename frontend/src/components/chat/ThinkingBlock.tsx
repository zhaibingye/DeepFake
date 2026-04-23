import { BrainCircuit } from 'lucide-react'

import { MarkdownView } from '../MarkdownView'
import type { TimelinePart } from '../../types'
import { TimelineBlock } from './TimelineBlock'

export function ThinkingBlock({
  part,
  open,
  onToggle,
}: {
  part: TimelinePart
  open: boolean
  onToggle: (nextOpen: boolean) => void
}) {
  const title = part.label || (part.status === 'running' ? '正在思考' : '思考过程')
  const meta = part.detail || (part.status === 'running' ? '模型正在组织答案' : undefined)

  return (
    <TimelineBlock
      part={part}
      title={title}
      meta={meta}
      icon={<BrainCircuit size={14} />}
      open={open}
      onToggle={onToggle}
    >
      <div className="timeline-markdown subtle">
        <MarkdownView content={part.text || '...'} enableMath={false} />
      </div>
    </TimelineBlock>
  )
}
