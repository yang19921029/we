import { useCallback, useEffect, useState } from 'react'
import {
  getPlatformUsers,
  updatePlatformUserRole,
  type PlatformUser,
} from '../../api'
import { PageTitle } from './PlatformShared'
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
  const roles = [
    '超级管理员',
    '项目管理员',
    '任务负责人',
    '标注员',
    '审核员',
    '数据分析员',
  ]

  const loadUsers = useCallback(async () => {
    setLoading(true)
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
      await updatePlatformUserRole(user.id, role)
      setUsers((current) =>
        current.map((entry) => entry.id === user.id ? { ...entry, role } : entry),
      )
      setMessage(`已更新 ${user.username} 的角色。`)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '角色更新失败。'))
      await loadUsers()
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="PEOPLE & ACCESS"
        title="人员与权限"
        description="为账号配置角色权限。系统至少保留一名管理员，服务端会校验敏感操作权限。"
      />
      {error && <p className="platform-error" role="alert">{error}</p>}
      {message && <p className="platform-success" role="status">{message}</p>}
      <section className="platform-table-card">
        <div className="section-title-row">
          <div><h2>用户与角色</h2><p>{users.length} 个账号</p></div>
          <button className="platform-secondary-button" onClick={() => void loadUsers()} type="button">刷新</button>
        </div>
        {loading ? (
          <p className="api-message" role="status">正在加载用户…</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr><th scope="col">账号</th><th scope="col">角色</th><th scope="col">权限范围</th></tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>
                      <select
                        aria-label={`${user.username}角色`}
                        onChange={(event) => void changeRole(user, event.target.value)}
                        value={user.role}
                      >
                        {roles.map((role) => <option key={role} value={role}>{role}</option>)}
                      </select>
                    </td>
                    <td>{user.role === '标注员' ? '执行分配任务' : user.role === '审核员' ? '审核与退回标注' : user.role === '数据分析员' ? '统计和数据导出' : user.role === '任务负责人' ? '管理数据集与任务' : '平台管理权限'}</td>
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
