import { type FormEvent, useState } from 'react'
import {
  login,
  resetForgottenPassword,
  sendForgotPasswordCode,
  type User,
} from '../api'

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  )
}

export default function LoginPage({
  onLogin,
  initialNotice = '',
}: {
  onLogin: (user: User) => void
  initialNotice?: string
}) {
  const [passwordVisible, setPasswordVisible] = useState(false)
  const [isForgotPassword, setIsForgotPassword] = useState(false)
  const [username, setUsername] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [notice, setNotice] = useState(initialNotice)
  const [isNoticeError, setIsNoticeError] = useState(Boolean(initialNotice))
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSendingCode, setIsSendingCode] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const accountName = String(formData.get('username') ?? '').trim()
    setNotice('')
    setIsNoticeError(false)
    setIsSubmitting(true)
    try {
      if (isForgotPassword) {
        const password = String(formData.get('new-password') ?? '')
        const confirmation = String(formData.get('confirm-password') ?? '')
        if (password.length < 8 || password.length > 256) {
          throw new Error('新密码长度须为 8 至 256 个字符。')
        }
        if (password !== confirmation) {
          throw new Error('两次输入的新密码不一致。')
        }
        await resetForgottenPassword(accountName, code.trim(), password)
        setIsForgotPassword(false)
        setCode('')
        setNewPassword('')
        setConfirmPassword('')
        setNotice('密码重置成功，请使用新密码登录。')
      } else {
        const password = String(formData.get('password') ?? '')
        const user = await login(accountName, password)
        onLogin(user)
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '登录失败，请重试。')
      setIsNoticeError(true)
    } finally {
      setIsSubmitting(false)
    }
  }

  function showDemoNotice() {
    setNotice('注册和找回密码功能尚未接入。')
    setIsNoticeError(false)
  }

  async function requestResetCode() {
    setNotice('')
    setIsNoticeError(false)
    if (!username.trim()) {
      setNotice('请先输入登录账号。')
      setIsNoticeError(true)
      return
    }
    setIsSendingCode(true)
    try {
      await sendForgotPasswordCode(username.trim())
      setNotice('如果账号已绑定验证邮箱，验证码将发送至该邮箱；否则请联系管理员重置密码。')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '验证码发送失败，请重试。')
      setIsNoticeError(true)
    } finally {
      setIsSendingCode(false)
    }
  }

  function showLogin() {
    setIsForgotPassword(false)
    setNotice('')
    setIsNoticeError(false)
  }

  return (
    <main className="page-shell">
      <section className="brand-panel" aria-label="系统介绍">
        <div className="brand-topline">
          <BrandMark />
          <span className="brand-label">数据标注管理平台</span>
        </div>

        <div className="brand-copy">
          <p className="brand-eyebrow">ALGORITHM FILING SERVICE</p>
          <h1>
            高质量数据
            <br />
            标注系统
          </h1>
          <p className="brand-description">
            管理标注任务与数据集，提升数据质量
            <br />
            让数据生产流程清晰、高效、可追溯
          </p>
        </div>

        <div className="brand-orbit orbit-one" aria-hidden="true" />
        <div className="brand-orbit orbit-two" aria-hidden="true" />
        <div className="brand-grid" aria-hidden="true" />
        <div className="brand-footer">安全 · 规范 · 可信</div>
      </section>

      <section className="login-panel" aria-labelledby="login-title">
        <div className="demo-banner">
          <span className="demo-dot" />
          登录信息将提交至服务端校验
        </div>

        <button className="back-link" type="button" onClick={showDemoNotice}>
          <span aria-hidden="true">←</span>
          返回首页
        </button>

        <div className="login-content">
          <header className="login-heading">
            <h2 id="login-title">{isForgotPassword ? '找回密码' : '欢迎登录'}</h2>
            <p>
              {isForgotPassword
                ? '使用已验证邮箱接收验证码并重置密码'
                : <>还没有账号？<button type="button" className="text-link" onClick={showDemoNotice}>去注册</button></>}
            </p>
          </header>

          <form className="login-form" onSubmit={handleSubmit}>
            <label className="form-field">
              <span className="field-label">账号 / 手机号</span>
              <input
                autoComplete="username"
                name="username"
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入账号或手机号"
                required
                type="text"
                value={username}
              />
            </label>

            {!isForgotPassword ? (
              <label className="form-field">
                <span className="field-label">密码</span>
                <span className="input-with-action">
                <input
                  autoComplete="current-password"
                  name="password"
                  placeholder="请输入您的密码"
                  required
                  type={passwordVisible ? 'text' : 'password'}
                />
                <button
                  aria-label={passwordVisible ? '隐藏密码' : '显示密码'}
                  className="icon-button"
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  type="button"
                >
                  {passwordVisible ? (
                    <svg aria-hidden="true" viewBox="0 0 24 24">
                      <path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8" />
                      <path d="M9.9 5.2A10.8 10.8 0 0112 5c5.2 0 8.6 5.4 8.6 7a8.8 8.8 0 01-2.2 3.2M6.2 6.2C3.9 7.6 2.4 10.3 2.4 12c0 1.6 3.8 7 9.6 7 1.1 0 2.1-.2 3-.5" />
                    </svg>
                  ) : (
                    <svg aria-hidden="true" viewBox="0 0 24 24">
                      <path d="M2.4 12s3.4-7 9.6-7 9.6 7 9.6 7-3.4 7-9.6 7-9.6-7-9.6-7z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
                </span>
              </label>
            ) : (
              <>
                <div className="forgot-code-row">
                  <label className="form-field">
                    <span className="field-label">邮箱验证码</span>
                    <input
                      autoComplete="one-time-code"
                      inputMode="numeric"
                      maxLength={6}
                      name="code"
                      onChange={(event) => setCode(event.target.value)}
                      pattern="[0-9]{6}"
                      placeholder="请输入 6 位验证码"
                      required
                      value={code}
                    />
                  </label>
                  <button
                    className="text-link forgot-send-code"
                    disabled={isSendingCode}
                    onClick={() => void requestResetCode()}
                    type="button"
                  >
                    {isSendingCode ? '发送中…' : '获取验证码'}
                  </button>
                </div>
                <label className="form-field">
                  <span className="field-label">新密码</span>
                  <input
                    autoComplete="new-password"
                    maxLength={256}
                    name="new-password"
                    onChange={(event) => setNewPassword(event.target.value)}
                    placeholder="至少 8 个字符"
                    required
                    type="password"
                    value={newPassword}
                  />
                </label>
                <label className="form-field">
                  <span className="field-label">确认新密码</span>
                  <input
                    autoComplete="new-password"
                    maxLength={256}
                    name="confirm-password"
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="请再次输入新密码"
                    required
                    type="password"
                    value={confirmPassword}
                  />
                </label>
              </>
            )}

            <div className="form-options">
              <span />
              <button
                className="text-link"
                type="button"
                onClick={() => {
                  if (isForgotPassword) showLogin()
                  else {
                    setIsForgotPassword(true)
                    setNotice('')
                    setIsNoticeError(false)
                  }
                }}
              >
                {isForgotPassword ? '返回登录' : '忘记密码？'}
              </button>
            </div>

            <button className="login-button" disabled={isSubmitting} type="submit">
              {isSubmitting ? (isForgotPassword ? '正在重置…' : '登录中…') : isForgotPassword ? '重置密码' : '登 录'}
            </button>
            <p
              aria-live="polite"
              className={`form-notice${isNoticeError ? ' is-error' : ''}`}
              role={isNoticeError ? 'alert' : undefined}
            >
              {notice}
            </p>
          </form>

          <p className="login-footnote">
            请使用已注册的账号登录本系统
          </p>
        </div>
      </section>
    </main>
  )
}
