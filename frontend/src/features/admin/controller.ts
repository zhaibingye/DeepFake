import type { Dispatch, SetStateAction } from 'react'

import { api } from '../../api'
import { normalizeThinkingEffort } from '../../appState'
import type {
  AdminManagedUser,
  AdminSettings,
  Provider,
  SearchProviderAvailability,
  SearchProviderKind,
  User,
} from '../../types'
import { defaultProviderForm, type ProviderFormState } from './providerForm'

export type SearchProviderFormState = {
  api_key: string
  is_enabled: boolean
}

export function buildSearchProviderForms(
  searchProviders: SearchProviderAvailability,
): Record<SearchProviderKind, SearchProviderFormState> {
  return {
    exa: {
      api_key: '',
      is_enabled: Boolean(searchProviders.exa?.is_enabled),
    },
    tavily: {
      api_key: '',
      is_enabled: Boolean(searchProviders.tavily?.is_enabled),
    },
  }
}

export async function loadAdminDataState(options: {
  token: string
  role?: User['role']
  setAdminProviders: Dispatch<SetStateAction<Provider[]>>
  setAdminSearchProviders: Dispatch<SetStateAction<SearchProviderAvailability | null>>
  setSearchProviderForms: Dispatch<
    SetStateAction<Record<SearchProviderKind, SearchProviderFormState>>
  >
  setAdminUsers: Dispatch<SetStateAction<AdminManagedUser[]>>
  setAdminSettings: Dispatch<SetStateAction<AdminSettings>>
}) {
  if (options.role !== 'admin') return
  const [providersList, searchProviders, usersList, settings] = await Promise.all([
    api.listAdminProviders(options.token),
    api.listAdminSearchProviders(options.token),
    api.listAdminUsers(options.token),
    api.getAdminSettings(options.token),
  ])
  options.setAdminProviders(providersList)
  options.setAdminSearchProviders(searchProviders)
  options.setSearchProviderForms(buildSearchProviderForms(searchProviders))
  options.setAdminUsers(usersList)
  options.setAdminSettings(settings)
}

export async function submitProviderState(options: {
  token: string
  editingProviderId: number | null
  providerForm: ProviderFormState
  setProviderError: Dispatch<SetStateAction<string>>
  setProviderSuccess: Dispatch<SetStateAction<string>>
  setProviderForm: Dispatch<SetStateAction<ProviderFormState>>
  setEditingProviderId: Dispatch<SetStateAction<number | null>>
  refreshAfterSave: () => Promise<void>
}) {
  options.setProviderError('')
  options.setProviderSuccess('')
  try {
    if (options.editingProviderId) {
      await api.updateProvider(options.token, options.editingProviderId, options.providerForm)
      options.setProviderSuccess('供应商已更新')
    } else {
      await api.createProvider(options.token, options.providerForm)
      options.setProviderSuccess('供应商已添加')
    }
    options.setProviderForm(defaultProviderForm)
    options.setEditingProviderId(null)
    await options.refreshAfterSave()
  } catch (error) {
    options.setProviderError(error instanceof Error ? error.message : '保存供应商失败')
  }
}

export async function removeProviderState(options: {
  token: string
  provider: Provider
  selectedProviderId: number | null
  applyProviderSelection: (nextProviderId: number | null) => void
  confirmDelete: () => Promise<boolean>
  setProviderError: Dispatch<SetStateAction<string>>
  setProviderSuccess: Dispatch<SetStateAction<string>>
  refreshAfterDelete: () => Promise<void>
}) {
  const confirmed = await options.confirmDelete()
  if (!confirmed) return
  options.setProviderError('')
  options.setProviderSuccess('')
  try {
    await api.deleteProvider(options.token, options.provider.id)
    options.setProviderSuccess('供应商已删除')
    if (options.selectedProviderId === options.provider.id) {
      options.applyProviderSelection(null)
    }
    await options.refreshAfterDelete()
  } catch (error) {
    options.setProviderError(error instanceof Error ? error.message : '删除供应商失败')
  }
}

export function buildEditingProviderForm(provider: Provider): ProviderFormState {
  return {
    name: provider.name,
    api_format: provider.api_format,
    api_url: '',
    api_key: '',
    model_name: provider.model_name,
    supports_thinking: provider.supports_thinking,
    supports_vision: provider.supports_vision,
    supports_tool_calling: provider.supports_tool_calling,
    thinking_effort: normalizeThinkingEffort(provider.thinking_effort, provider.api_format),
    max_context_window: provider.max_context_window,
    max_output_tokens: provider.max_output_tokens,
    is_enabled: provider.is_enabled,
  }
}

export async function submitAdminProfileState(options: {
  token: string
  adminProfile: { username: string; current_password: string; new_password: string }
  setUser: Dispatch<SetStateAction<User | null>>
  setAdminProfile: Dispatch<
    SetStateAction<{ username: string; current_password: string; new_password: string }>
  >
  setAdminProfileMessage: Dispatch<SetStateAction<string>>
}) {
  options.setAdminProfileMessage('')
  try {
    const updated = await api.updateAdminProfile(options.token, options.adminProfile)
    options.setUser(updated)
    options.setAdminProfile({
      username: updated.username,
      current_password: '',
      new_password: '',
    })
    options.setAdminProfileMessage('管理员账号已更新')
  } catch (error) {
    options.setAdminProfileMessage(error instanceof Error ? error.message : '更新管理员失败')
  }
}

export async function submitSearchProviderState(options: {
  token: string
  kind: SearchProviderKind
  form: SearchProviderFormState
  setAdminSearchProviders: Dispatch<SetStateAction<SearchProviderAvailability | null>>
  setSearchProviderForms: Dispatch<
    SetStateAction<Record<SearchProviderKind, SearchProviderFormState>>
  >
  setMessage: Dispatch<SetStateAction<string>>
  setError: Dispatch<SetStateAction<boolean>>
}) {
  options.setMessage('')
  options.setError(false)
  try {
    const updated = await api.updateAdminSearchProvider(options.token, options.kind, options.form)
    options.setAdminSearchProviders((prev) => {
      if (!prev) {
        return {
          exa: options.kind === 'exa' ? updated : { is_enabled: true, is_configured: true },
          tavily:
            options.kind === 'tavily' ? updated : { is_enabled: false, is_configured: false },
        }
      }
      return {
        ...prev,
        [options.kind]: updated,
      }
    })
    options.setSearchProviderForms((prev) => ({
      ...prev,
      [options.kind]: {
        ...prev[options.kind],
        api_key: '',
        is_enabled: updated.is_enabled,
      },
    }))
    options.setMessage(`${updated.name ?? options.kind} 搜索配置已保存`)
  } catch (error) {
    options.setError(true)
    options.setMessage(error instanceof Error ? error.message : '保存搜索配置失败')
  }
}

export async function toggleAllowRegistrationState(options: {
  token: string
  value: boolean
  setAdminSettings: Dispatch<SetStateAction<AdminSettings>>
  setUserAdminMessage: Dispatch<SetStateAction<string>>
  setUserAdminError: Dispatch<SetStateAction<boolean>>
}) {
  options.setUserAdminMessage('')
  options.setUserAdminError(false)
  try {
    const settings = await api.updateAdminSettings(options.token, {
      allow_registration: options.value,
    })
    options.setAdminSettings(settings)
    options.setUserAdminMessage(settings.allow_registration ? '已开启用户注册' : '已关闭用户注册')
  } catch (error) {
    options.setUserAdminError(true)
    options.setUserAdminMessage(error instanceof Error ? error.message : '更新注册设置失败')
  }
}

export async function submitAdminUserState(options: {
  token: string
  userForm: { username: string; password: string; role: 'admin' | 'user'; is_enabled: boolean }
  setAdminUsers: Dispatch<SetStateAction<AdminManagedUser[]>>
  setUserForm: Dispatch<
    SetStateAction<{ username: string; password: string; role: 'admin' | 'user'; is_enabled: boolean }>
  >
  setUserAdminMessage: Dispatch<SetStateAction<string>>
  setUserAdminError: Dispatch<SetStateAction<boolean>>
}) {
  options.setUserAdminMessage('')
  options.setUserAdminError(false)
  try {
    const created = await api.createAdminUser(options.token, options.userForm)
    options.setAdminUsers((prev) => [created, ...prev])
    options.setUserForm({ username: '', password: '', role: 'user', is_enabled: true })
    options.setUserAdminMessage('用户已创建')
  } catch (error) {
    options.setUserAdminError(true)
    options.setUserAdminMessage(error instanceof Error ? error.message : '创建用户失败')
  }
}

export async function toggleUserEnabledState(options: {
  token: string
  targetUser: AdminManagedUser
  currentUserId?: number
  onSelfDisabled: () => void
  setAdminUsers: Dispatch<SetStateAction<AdminManagedUser[]>>
  setUserAdminMessage: Dispatch<SetStateAction<string>>
  setUserAdminError: Dispatch<SetStateAction<boolean>>
}) {
  options.setUserAdminMessage('')
  options.setUserAdminError(false)
  try {
    const updated = await api.updateAdminUser(options.token, options.targetUser.id, {
      is_enabled: !options.targetUser.is_enabled,
    })
    options.setAdminUsers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    if (options.currentUserId === updated.id && !updated.is_enabled) {
      options.onSelfDisabled()
      return
    }
    options.setUserAdminMessage(updated.is_enabled ? '用户已启用' : '用户已停用')
  } catch (error) {
    options.setUserAdminError(true)
    options.setUserAdminMessage(error instanceof Error ? error.message : '更新用户状态失败')
  }
}

export async function removeAdminUserState(options: {
  token: string
  targetUser: AdminManagedUser
  confirmDelete: () => Promise<boolean>
  setAdminUsers: Dispatch<SetStateAction<AdminManagedUser[]>>
  setUserAdminMessage: Dispatch<SetStateAction<string>>
  setUserAdminError: Dispatch<SetStateAction<boolean>>
}) {
  const confirmed = await options.confirmDelete()
  if (!confirmed) return
  options.setUserAdminMessage('')
  options.setUserAdminError(false)
  try {
    await api.deleteAdminUser(options.token, options.targetUser.id)
    options.setAdminUsers((prev) => prev.filter((item) => item.id !== options.targetUser.id))
    options.setUserAdminMessage('用户已删除')
  } catch (error) {
    options.setUserAdminError(true)
    options.setUserAdminMessage(error instanceof Error ? error.message : '删除用户失败')
  }
}

export async function resetAdminUserPasswordState(options: {
  token: string
  targetUser: AdminManagedUser
  password: string
  setUserAdminMessage: Dispatch<SetStateAction<string>>
  setUserAdminError: Dispatch<SetStateAction<boolean>>
}) {
  options.setUserAdminMessage('')
  options.setUserAdminError(false)
  try {
    await api.resetAdminUserPassword(options.token, options.targetUser.id, {
      new_password: options.password,
    })
    options.setUserAdminMessage('用户密码已重置，原有登录状态已失效')
  } catch (error) {
    options.setUserAdminError(true)
    options.setUserAdminMessage(error instanceof Error ? error.message : '重置密码失败')
  }
}
