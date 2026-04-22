import ReactMarkdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'

type Props = {
  content: string
  enableMath?: boolean
}

export function MarkdownView({ content, enableMath = true }: Props) {
  const remarkPlugins = enableMath ? [remarkGfm, remarkMath] : [remarkGfm]
  const rehypePlugins = enableMath ? [rehypeKatex] : []

  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
      {content}
    </ReactMarkdown>
  )
}
