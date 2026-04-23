import { Wrench } from 'lucide-react'

import { MarkdownView } from '../MarkdownView'
import type { TimelinePart } from '../../types'
import { TimelineBlock } from './TimelineBlock'

export function ToolBlock({
  part,
  open,
  onToggle,
}: {
  part: TimelinePart
  open: boolean
  onToggle: (nextOpen: boolean) => void
}) {
  const title = part.label || part.tool_name || '工具调用'
  const meta =
    part.detail || (part.status === 'running' ? '等待工具返回结果' : part.status === 'error' ? '工具调用失败' : undefined)

  return (
    <TimelineBlock
      part={part}
      title={title}
      meta={meta}
      icon={<Wrench size={14} />}
      open={open}
      onToggle={onToggle}
    >
      {part.input ? <pre className="timeline-code-block">{part.input}</pre> : null}
      <div className="timeline-markdown compact">
        <MarkdownView content={part.output || part.detail || '...'} enableMath={false} />
      </div>
    </TimelineBlock>
  )
}
