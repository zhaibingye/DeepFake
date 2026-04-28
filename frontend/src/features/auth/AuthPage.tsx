import { CheckCircle2, KeyRound, Loader2, ShieldCheck, Sparkles, UserRound } from 'lucide-react'

import type { AuthMode } from '../../appState'
import type { AdminSettings, SetupStatus } from '../../types'

type AuthPageProps = {
  authMode: AuthMode
  effectiveAuthMode: AuthMode
  authUsername: string
  authPassword: string
  setupPasswordConfirm: string
  authError: string
  loadingAuth: boolean
  publicAuthSettings: AdminSettings
  setupStatus: SetupStatus
  setupStatusLoaded: boolean
  setAuthMode: (mode: AuthMode) => void
  setAuthUsername: (value: string) => void
  setAuthPassword: (value: string) => void
  setSetupPasswordConfirm: (value: string) => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

export function AuthPage({
  authMode,
  effectiveAuthMode,
  authUsername,
  authPassword,
  setupPasswordConfirm,
  authError,
  loadingAuth,
  publicAuthSettings,
  setupStatus,
  setupStatusLoaded,
  setAuthMode,
  setAuthUsername,
  setAuthPassword,
  setSetupPasswordConfirm,
  onSubmit,
}: AuthPageProps) {
  const trimmedUsername = authUsername.trim()
  const setupChecks = [
    { label: '用户名为 3 到 32 个字符', done: trimmedUsername.length >= 3 && trimmedUsername.length <= 32 },
    { label: '密码至少 6 个字符', done: authPassword.length >= 6 },
    { label: '两次输入的密码一致', done: authPassword.length > 0 && authPassword === setupPasswordConfirm },
  ]
  const setupReady = setupChecks.every((item) => item.done)

  if (!setupStatusLoaded) {
    return (
      <div className="auth-shell">
        <div className="auth-card auth-loading-card">
          <div className="brand-mark"><Loader2 className="spin-icon" size={18} /></div>
          <div>
            <h1>正在检查系统状态</h1>
            <p className="hint-text">请稍候，正在确认是否需要初始化管理员账号。</p>
          </div>
        </div>
      </div>
    )
  }

  if (setupStatus.needs_admin_setup) {
    return (
      <div className="setup-shell">
        <main className="setup-page">
          <section className="setup-intro" aria-labelledby="setup-title">
            <div className="brand-mark solid"><ShieldCheck size={20} /></div>
            <div className="setup-copy">
              <span className="setup-eyebrow">首次启动</span>
              <h1 id="setup-title">创建第一个管理员</h1>
              <p>该账号会拥有后台配置、用户管理和供应商管理权限。创建成功后会自动进入应用。</p>
            </div>
            <div className="setup-progress" aria-label="初始化检查项">
              {setupChecks.map((item) => (
                <div className={item.done ? 'setup-check done' : 'setup-check'} key={item.label}>
                  <CheckCircle2 size={16} />
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="setup-form-card" aria-label="管理员初始化表单">
            <div className="setup-form-heading">
              <div>
                <h2>管理员账号</h2>
                <p>只在系统尚未创建任何管理员时开放。</p>
              </div>
            </div>
            <form className="auth-form setup-form" onSubmit={onSubmit}>
              <label>
                用户名
                <div className="input-with-icon">
                  <UserRound size={17} />
                  <input autoComplete="username" id="setup-admin-username" maxLength={32} name="username" value={authUsername} onChange={(event) => setAuthUsername(event.target.value)} placeholder="例如 admin" />
                </div>
              </label>
              <label>
                密码
                <div className="input-with-icon">
                  <KeyRound size={17} />
                  <input autoComplete="new-password" id="setup-admin-password" maxLength={128} name="password" type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="至少 6 个字符" />
                </div>
              </label>
              <label>
                确认密码
                <div className="input-with-icon">
                  <KeyRound size={17} />
                  <input autoComplete="new-password" id="setup-admin-password-confirm" maxLength={128} name="password_confirm" type="password" value={setupPasswordConfirm} onChange={(event) => setSetupPasswordConfirm(event.target.value)} placeholder="再次输入密码" />
                </div>
              </label>
              {authError ? <div className="error-text">{authError}</div> : null}
              <button className="primary-btn setup-submit" disabled={loadingAuth || !setupReady} type="submit">
                {loadingAuth ? '正在创建...' : '创建管理员并进入'}
              </button>
            </form>
          </section>
        </main>
      </div>
    )
  }

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
        <div className="auth-tabs">
          <button className={effectiveAuthMode === 'login' ? 'active' : ''} onClick={() => setAuthMode('login')} type="button">登录</button>
          <button className={effectiveAuthMode === 'register' ? 'active' : ''} disabled={!publicAuthSettings.allow_registration} onClick={() => setAuthMode('register')} type="button">注册</button>
        </div>
        <form className="auth-form" onSubmit={onSubmit}>
          <label>
            用户名
            <input autoComplete="username" id="auth-username" name="username" value={authUsername} onChange={(event) => setAuthUsername(event.target.value)} placeholder="输入用户名" />
          </label>
          <label>
            密码
            <input autoComplete={effectiveAuthMode === 'register' ? 'new-password' : 'current-password'} id="auth-password" name="password" type="password" value={authPassword} onChange={(event) => setAuthPassword(event.target.value)} placeholder="输入密码" />
          </label>
          {authError ? <div className="error-text">{authError}</div> : null}
          <button className="primary-btn" disabled={loadingAuth} type="submit">
            {loadingAuth ? '处理中...' : effectiveAuthMode === 'login' ? '登录' : '注册并进入'}
          </button>
          {!publicAuthSettings.allow_registration && authMode === 'register' ? (
            <div className="hint-text">当前已关闭普通用户注册</div>
          ) : !publicAuthSettings.allow_registration ? (
            <div className="hint-text">当前已关闭普通用户注册</div>
          ) : null}
        </form>
      </div>
    </div>
  )
}
