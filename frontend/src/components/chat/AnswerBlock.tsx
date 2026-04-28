import { MarkdownView } from '../MarkdownView'
import type { TimelinePart } from '../../types'

export function AnswerBlock({ part }: { part: TimelinePart }) {
  return (
    <div className={part.status === 'running' ? 'message-bubble assistant streaming' : 'message-bubble assistant'}>
      <div className="markdown-body">
        <MarkdownView content={part.text || '...'} />
      </div>
    </div>
  )
}
