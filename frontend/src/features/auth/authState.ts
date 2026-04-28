import { api } from '../../api'
import type { AdminSettings, SetupStatus, User } from '../../types'

export async function refreshAuthSurfaceState(): Promise<{
  settings: AdminSettings
  setupStatus: SetupStatus
}> {
  const [settings, setupStatus] = await Promise.all([
    api.authSettings(),
    api.setupStatus(),
  ])

  return { settings, setupStatus }
}

export async function authenticateUserState(options: {
  needsAdminSetup: boolean
  authMode: 'login' | 'register'
  username: string
  password: string
}): Promise<{ token: string; user: User }> {
  if (options.needsAdminSetup) {
    return api.setupAdmin(options.username, options.password)
  }

  if (options.authMode === 'login') {
    return api.login(options.username, options.password)
  }

  return api.register(options.username, options.password)
}
