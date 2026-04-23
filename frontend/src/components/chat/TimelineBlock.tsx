import type { PropsWithChildren, ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'

import type { TimelinePart } from '../../types'

export function TimelineBlock({
  part,
  title,
  meta,
  icon,
  open,
  onToggle,
  children,
}: PropsWithChildren<{
  part: TimelinePart
  title: string
  meta?: string
  icon: ReactNode
  open: boolean
  onToggle: (nextOpen: boolean) => void
}>) {
  return (
    <details
      className={`timeline-block ${part.kind} ${part.status}`}
      open={open}
    >
      <summary
        className="timeline-block-summary"
        onClick={(event) => {
          event.preventDefault()
          onToggle(!open)
        }}
      >
        <span className="timeline-block-summary-copy">
          <span className="timeline-block-summary-icon">{icon}</span>
          <span className="timeline-block-summary-text">
            <strong className="timeline-block-title">{title}</strong>
            {meta ? <small className="timeline-block-meta">{meta}</small> : null}
          </span>
        </span>
        <ChevronRight className="timeline-block-chevron" size={14} />
      </summary>
      <div className="timeline-block-body">{children}</div>
    </details>
  )
}
