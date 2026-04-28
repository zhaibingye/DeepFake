import type { SearchProviderKind, SearchProviderStatus } from '../../types'

export type SearchProviderLoadState = 'loading' | 'ready' | 'error'

export const searchProviderOptions: SearchProviderKind[] = ['exa', 'tavily']

export function searchProviderLabel(kind: SearchProviderKind) {
  return kind === 'exa' ? 'Exa' : 'Tavily'
}

export function isSearchProviderAvailable(status?: SearchProviderStatus | null) {
  return Boolean(status?.is_enabled && status?.is_configured)
}

export function getSearchProviderUnavailableReason(
  kind: SearchProviderKind,
  status?: SearchProviderStatus | null,
  loadState: SearchProviderLoadState = 'ready',
) {
  if (loadState === 'loading') return '搜索源状态加载中，请稍后重试'
  if (loadState === 'error') return '搜索源状态获取失败，请稍后重试'
  if (!status) return '搜索源状态获取失败，请稍后重试'
  if (status.is_enabled && status.is_configured) return ''
  if (kind === 'tavily' && !status.is_configured) {
    return 'Tavily 搜索当前不可用，请先在后台配置'
  }
  return `${searchProviderLabel(kind)} 搜索当前不可用`
}
