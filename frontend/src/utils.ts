import type { Attachment, TimelinePart } from './types'

type MessageContent = string | Array<Record<string, unknown>> | { parts: TimelinePart[] }

export function formatDateTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function messagePlainText(content: MessageContent) {
  if (typeof content === 'string') {
    return content
  }
  if (!Array.isArray(content)) {
    return content.parts
      .filter((part) => part.kind === 'answer' && typeof part.text === 'string')
      .map((part) => part.text ?? '')
      .join('\n\n')
  }
  return content
    .filter((item) => item.type === 'text' && typeof item.text === 'string')
    .map((item) => String(item.text))
    .join('\n\n')
}

export function messageImages(content: MessageContent) {
  if (typeof content === 'string') {
    return []
  }
  if (!Array.isArray(content)) {
    return []
  }

  return content
    .filter((item) => item.type === 'image' && typeof item.source === 'object' && item.source !== null)
    .map((item) => {
      const source = item.source as { media_type?: string; data?: string }
      return {
        media_type: source.media_type ?? 'image/png',
        data: source.data ?? '',
      }
    })
    .filter((item) => item.data)
}

export function fileToAttachment(file: File): Promise<Attachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result)
      const [, base64] = result.split(',')
      resolve({
        name: file.name,
        media_type: file.type || inferMediaType(file.name),
        data: base64,
      })
    }
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.readAsDataURL(file)
  })
}

function inferMediaType(name: string) {
  const lower = name.toLowerCase()
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg'
  if (lower.endsWith('.png')) return 'image/png'
  if (lower.endsWith('.gif')) return 'image/gif'
  if (lower.endsWith('.webp')) return 'image/webp'
  return 'application/octet-stream'
}
