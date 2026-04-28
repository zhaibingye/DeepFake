import { Sparkles } from 'lucide-react'

import type { AuthMode } from '../../appState'
import type { AdminSettings, SetupStatus } from '../../types'

type AuthPageProps = {
  authMode: AuthMode
  effectiveAuthMode: AuthMode
  authUsername: string
  authPassword: string
  authError: string
  loadingAuth: boolean
  publicAuthSettings: AdminSettings
  setupStatus: SetupStatus
  setupStatusLoaded: boolean
  setAuthMode: (mode: AuthMode) => void
  setAuthUsername: (value: string) => void
  setAuthPassword: (value: string) => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

export function AuthPage({
  authMode,
  effectiveAuthMode,
  authUsername,
  authPassword,
  authError,
  loadingAuth,
  publicAuthSettings,
  setupStatus,
  setupStatusLoaded,
  setAuthMode,
  setAuthUsername,
  setAuthPassword,
  onSubmit,
}: AuthPageProps) {
  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="brand-mark"><Sparkles size={18} /></div>
          <div>
            <h1>deepfake</h1>
            <p>极简聊天界面，多用户与后台配置分离。</p>
          </div>
        </div>
        {!setupStatusLoaded ? (
          <div className="hint-text">正在检查系统初始化状态...</div>
        ) : (
          <>
            {setupStatus.needs_admin_setup ? (
              <div className="hint-text">当前还没有管理员账号，请先初始化首个管理员。</div>
            ) : (
              <div className="auth-tabs">
                <button className={effectiveAuthMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')} type="button">登录</button>
                <button className={effectiveAuthMode === 'register' ? 'active' : ''} disabled={!publicAuthSettings.allow_registration} onClick={() => setAuthMode('register')} type="button">注册</button>
              </div>
            )}
            <form className="auth-form" onSubmit={onSubmit}>
              <label>
                用户名
                <input autoComplete="username" id="auth-username" name="username" value={authUsername} onChange={(event) => setAuthUsername(event.target.value)} placeholder={setupStatus.needs_admin_setup ? '输入管理员用户名' : '输入用户名'} />
              </label>
              <label>
                密码
                <input autoComplete={setupStatus.needs_admin_setup || effectiveAuthMode === 'register' ? 'new-password' : 'current-password'} id="auth-password" name="password" type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder={setupStatus.needs_admin_setup ? '设置管理员密码' : '输入密码'} />
              </label>
              {authError ? <div className="error-text">{authError}</div> : null}
              <button className="primary-btn" disabled={loadingAuth} type="submit">
                {loadingAuth ? '处理中...' : setupStatus.needs_admin_setup ? '创建管理员并进入' : effectiveAuthMode === 'login' ? '登录' : '注册并进入'}
              </button>
              {setupStatus.needs_admin_setup ? (
                <div className="hint-text">该入口只在系统尚未创建任何管理员时开放。</div>
              ) : !publicAuthSettings.allow_registration && authMode === 'register' ? (
                <div className="hint-text">当前已关闭普通用户注册</div>
              ) : !publicAuthSettings.allow_registration ? (
                <div className="hint-text">当前已关闭普通用户注册</div>
              ) : null}
            </form>
          </>
        )}
      </div>
    </div>
  )
}
