import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  changeCurrentPassword,
  getRecoveryEmail,
  sendRecoveryEmailCode,
  verifyRecoveryEmail,
} from '../../api'
import { PlatformModal } from './PlatformModal'

export function AccountSecurityModal({
  onClose,
}: {
  onClose: () => void
}) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [verifiedEmail, setVerifiedEmail] = useState<string | null>(null)
  const [passwordMessage, setPasswordMessage] = useState('')
  const [emailMessage, setEmailMessage] = useState('')
  const [error, setError] = useState('')
  const [loadingEmail, setLoadingEmail] = useState(true)
  const [savingPassword, setSavingPassword] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [verifyingEmail, setVerifyingEmail] = useState(false)

  const loadRecoveryEmail = useCallback(async () => {
    try {
      const result = await getRecoveryEmail()
      setVerifiedEmail(result.verified ? result.email : null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '恢复邮箱读取失败。')
    } finally {
      setLoadingEmail(false)
    }
  }, [])

  useEffect(() => {
    void loadRecoveryEmail()
  }, [loadRecoveryEmail])

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setPasswordMessage('')
    if (newPassword.length < 8 || newPassword.length > 256) {
      setError('新密码长度须为 8 至 256 个字符。')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }
    setSavingPassword(true)
    try {
      await changeCurrentPassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMessage('密码已修改成功。')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '密码修改失败。')
    } finally {
      setSavingPassword(false)
    }
  }

  async function requestEmailCode() {
    setError('')
    setEmailMessage('')
    setSendingCode(true)
    try {
      await sendRecoveryEmailCode(email.trim())
      setEmailMessage('验证码已发送，请查收邮件；验证码 10 分钟内有效。')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '验证码发送失败。')
    } finally {
      setSendingCode(false)
    }
  }

  async function confirmEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setEmailMessage('')
    setVerifyingEmail(true)
    try {
      await verifyRecoveryEmail(email.trim(), code.trim())
      const [name, domain] = email.trim().toLowerCase().split('@')
      setVerifiedEmail(`${name.slice(0, 1)}***@${domain}`)
      setEmail('')
      setCode('')
      setEmailMessage('恢复邮箱验证并绑定成功。')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '邮箱验证失败。')
    } finally {
      setVerifyingEmail(false)
    }
  }

  return (
    <PlatformModal onClose={onClose} title="账号安全">
      {error && <p className="platform-error" role="alert">{error}</p>}
      <form className="platform-form-card account-security-form" onSubmit={(event) => void submitPassword(event)}>
        <h3>修改密码</h3>
        <label>
          当前密码
          <input
            autoComplete="current-password"
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
            type="password"
            value={currentPassword}
          />
        </label>
        <label>
          新密码（8 至 256 个字符）
          <input
            autoComplete="new-password"
            maxLength={256}
            onChange={(event) => setNewPassword(event.target.value)}
            required
            type="password"
            value={newPassword}
          />
        </label>
        <label>
          确认新密码
          <input
            autoComplete="new-password"
            maxLength={256}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
            type="password"
            value={confirmPassword}
          />
        </label>
        <button className="welcome-action" disabled={savingPassword} type="submit">
          {savingPassword ? '正在修改…' : '修改密码'}
        </button>
        {passwordMessage && <p className="platform-success" role="status">{passwordMessage}</p>}
      </form>

      <form className="platform-form-card account-security-form" onSubmit={(event) => void confirmEmail(event)}>
        <h3>找回密码邮箱</h3>
        {loadingEmail ? (
          <p className="api-message" role="status">正在读取邮箱状态…</p>
        ) : verifiedEmail ? (
          <p className="account-security-email">
            已验证邮箱：<strong>{verifiedEmail}</strong>
          </p>
        ) : (
          <>
            <p className="platform-form-hint">
              找回密码时将向此邮箱发送验证码。请绑定本人可访问的邮箱。
            </p>
            <label>
              邮箱地址
              <input
                autoComplete="email"
                maxLength={254}
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
            <div className="account-security-code-row">
              <label>
                邮箱验证码
                <input
                  autoComplete="one-time-code"
                  inputMode="numeric"
                  maxLength={6}
                  onChange={(event) => setCode(event.target.value)}
                  pattern="[0-9]{6}"
                  required
                  value={code}
                />
              </label>
              <button
                className="platform-secondary-button"
                disabled={sendingCode || !email.trim()}
                onClick={() => void requestEmailCode()}
                type="button"
              >
                {sendingCode ? '发送中…' : '发送验证码'}
              </button>
            </div>
            <button className="welcome-action" disabled={verifyingEmail} type="submit">
              {verifyingEmail ? '正在验证…' : '验证并绑定邮箱'}
            </button>
          </>
        )}
        {emailMessage && <p className="platform-success" role="status">{emailMessage}</p>}
      </form>
    </PlatformModal>
  )
}
