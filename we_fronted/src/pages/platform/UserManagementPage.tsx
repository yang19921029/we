import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createPlatformUser,
  getPlatformUsers,
  updatePlatformUser,
  type PlatformUser,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { PlatformModal } from './PlatformModal'
import { handlePageError } from '../pageErrors'

export function UserManagementPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [users, setUsers] = useState<PlatformUser[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editingUser, setEditingUser] = useState<PlatformUser | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [role, setRole] = useState('标注员')
  const roles = [
    '超级管理员',
    '项目管理员',
    '任务负责人',
    '标注员',
    '审核员',
    '数据分析员',
  ]
  const loadUsers = useCallback(async () => {
    setError('')
    try {
      setUsers(await getPlatformUsers())
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '用户列表加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  async function changeRole(user: PlatformUser, role: string) {
    setError('')
    setMessage('')
    try {
      const updated = await updatePlatformUser(user.id, { role })
      setUsers((current) =>
        current.map((entry) => entry.id === user.id ? { ...entry, ...updated } : entry),
      )
      setMessage(`已更新 ${user.username} 的角色。`)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '角色更新失败。'))
      await loadUsers()
    }
  }

  function closeEditor() {
    setEditingUser(null)
    setIsCreating(false)
    setUsername('')
    setPassword('')
    setPasswordError('')
    setRole('标注员')
  }

  function startCreate() {
    setError('')
    setMessage('')
    setEditingUser(null)
    setIsCreating(true)
    setUsername('')
    setPassword('')
    setPasswordError('')
    setRole('标注员')
  }

  function startEdit(user: PlatformUser) {
    setError('')
    setMessage('')
    setIsCreating(false)
    setEditingUser(user)
    setUsername(user.username)
    setPassword('')
    setPasswordError('')
    setRole(user.role)
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!username.trim()) {
      setError('请填写登录账号。')
      return
    }
    if ((isCreating || password) && password.length < 8) {
      setPasswordError('密码至少需要 8 个字符。')
      return
    }
    setPasswordError('')
    setSaving(true)
    setError('')
    setMessage('')
    try {
      if (isCreating) {
        const created = await createPlatformUser({
          username: username.trim(),
          password,
          role,
        })
        setUsers((current) => [...current, created].sort((a, b) => a.username.localeCompare(b.username)))
        setMessage(`账号 ${created.username} 已创建。`)
      } else if (editingUser) {
        const changes: { username: string; role: string; password?: string } = {
          username: username.trim(),
          role,
        }
        if (password) changes.password = password
        const updated = await updatePlatformUser(editingUser.id, changes)
        setUsers((current) =>
          current.map((entry) => entry.id === updated.id ? { ...entry, ...updated } : entry),
        )
        setMessage(`账号 ${updated.username} 已更新。`)
      }
      closeEditor()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '用户信息保存失败。'))
    } finally {
      setSaving(false)
    }
  }

  async function toggleActive(user: PlatformUser) {
    const isActive = user.is_active !== false
    const action = isActive ? '禁用' : '启用'
    if (isActive && !window.confirm(`确定禁用账号“${user.username}”吗？该账号将立即退出并无法登录。`)) {
      return
    }
    setError('')
    setMessage('')
    try {
      const updated = await updatePlatformUser(user.id, { is_active: !isActive })
      setUsers((current) =>
        current.map((entry) => entry.id === updated.id ? { ...entry, ...updated } : entry),
      )
      setMessage(`已${action}账号 ${updated.username}。`)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, `账号${action}失败。`))
      await loadUsers()
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="PEOPLE & ACCESS"
        title="人员与权限"
        description="创建和维护平台账号、配置角色权限、重置密码或禁用账号。禁用会立即终止该账号的登录状态并保留历史记录。"
      />
      {error && <p className="platform-error" role="alert">{error}</p>}
      {message && <p className="platform-success" role="status">{message}</p>}
      {(isCreating || editingUser) && (
        <PlatformModal
          onClose={closeEditor}
          title={isCreating ? '新增人员' : '编辑人员'}
        >
          <form className="platform-form-card user-editor-form" noValidate onSubmit={(event) => void submitUser(event)}>
          <label>
            登录账号
            <input
              autoComplete="username"
              maxLength={191}
              onChange={(event) => setUsername(event.target.value)}
              required
              value={username}
            />
          </label>
          <label>
            {isCreating ? '初始密码（至少 8 个字符）' : '重置密码（至少 8 个字符；留空表示不修改）'}
            <input
              aria-describedby={passwordError ? 'user-password-error' : 'user-password-hint'}
              aria-invalid={Boolean(passwordError)}
              autoComplete="new-password"
              onChange={(event) => {
                setPassword(event.target.value)
                setPasswordError('')
              }}
              type="password"
              value={password}
            />
            <span className="platform-form-hint" id="user-password-hint">
              {isCreating ? '请输入至少 8 个字符的初始密码。' : '仅在需要重置密码时填写；新密码至少 8 个字符。'}
            </span>
            {passwordError && <span className="platform-error" id="user-password-error" role="alert">{passwordError}</span>}
          </label>
          <label>
            账号角色
            <select onChange={(event) => setRole(event.target.value)} value={role}>
              {roles.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button className="welcome-action" disabled={saving} type="submit">
            {saving ? '正在保存…' : isCreating ? '创建账号' : '保存修改'}
          </button>
          </form>
        </PlatformModal>
      )}
      <section className="platform-table-card user-management-card">
        <div className="section-title-row">
          <div><h2>人员账号</h2><p>{users.length} 个账号 · {users.filter((user) => user.is_active !== false).length} 个启用</p></div>
          <div className="user-table-actions">
            <button
              className="platform-secondary-button"
              onClick={() => {
                setLoading(true)
                void loadUsers()
              }}
              type="button"
            >
              刷新
            </button>
            <button className="welcome-action" onClick={startCreate} type="button">新增人员</button>
          </div>
        </div>
        {loading ? (
          <p className="api-message" role="status">正在加载用户…</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table user-management-table">
              <thead>
                <tr><th scope="col">账号</th><th scope="col">角色 / 权限</th><th scope="col">状态</th><th scope="col">操作</th></tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>
                      <div className="user-role-permission">
                        <select
                          aria-label={`${user.username}角色`}
                          onChange={(event) => void changeRole(user, event.target.value)}
                          value={user.role}
                        >
                          {roles.map((role) => <option key={role} value={role}>{role}</option>)}
                        </select>
                        <span className="user-permission-summary">
                          {user.role === '标注员' ? '执行分配任务' : user.role === '审核员' ? '审核与退回标注' : user.role === '数据分析员' ? '统计和数据导出' : user.role === '任务负责人' ? '管理数据集与任务' : '平台管理权限'}
                        </span>
                      </div>
                    </td>
                    <td>{user.is_active === false ? '已禁用' : '启用'}</td>
                    <td>
                      <div className="user-row-actions">
                        <button className="platform-secondary-button" onClick={() => startEdit(user)} type="button">编辑 / 重置密码</button>
                        <button
                          className="platform-secondary-button"
                          onClick={() => void toggleActive(user)}
                          type="button"
                        >
                          {user.is_active === false ? '启用' : '禁用'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
