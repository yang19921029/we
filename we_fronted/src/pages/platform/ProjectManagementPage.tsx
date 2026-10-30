import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addProjectMember,
  createOrganization,
  createProject,
  getOrganizations,
  getPlatformUsers,
  getProjectMembers,
  getProjects,
  removeProjectMember,
  type OrganizationRecord,
  type ProjectRecord,
  type ProjectMember,
  type PlatformUser,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function ProjectManagementPage({
  onSessionExpired,
  role,
}: {
  onSessionExpired: () => void
  role: string
}) {
  const [organizations, setOrganizations] = useState<OrganizationRecord[]>([])
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [users, setUsers] = useState<PlatformUser[]>([])
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [organizationName, setOrganizationName] = useState('')
  const [organizationDescription, setOrganizationDescription] = useState('')
  const [projectName, setProjectName] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [organizationId, setOrganizationId] = useState('')
  const [selectedProjectId, setSelectedProjectId] = useState('')
  const [memberUserId, setMemberUserId] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const canManageProjects = role === '超级管理员' || role === '项目管理员'

  const loadProjects = useCallback(async () => {
    setError('')
    try {
      const [nextOrganizations, nextProjects, nextUsers] = await Promise.all([
        getOrganizations(),
        getProjects(),
        canManageProjects ? getPlatformUsers() : Promise.resolve([]),
      ])
      setOrganizations(nextOrganizations)
      setProjects(nextProjects)
      setUsers(nextUsers)
      setOrganizationId((current) => current || String(nextOrganizations[0]?.id ?? ''))
      setSelectedProjectId((current) => current || String(nextProjects[0]?.id ?? ''))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '组织和项目加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [canManageProjects, onSessionExpired])

  useEffect(() => {
    void loadProjects()
  }, [loadProjects])

  useEffect(() => {
    if (!selectedProjectId) {
      setMembers([])
      return
    }
    const controller = new AbortController()
    void getProjectMembers(Number(selectedProjectId), controller.signal)
      .then(setMembers)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(handlePageError(cause, onSessionExpired, '项目成员加载失败。'))
      })
    return () => controller.abort()
  }, [onSessionExpired, selectedProjectId])

  async function addMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedProjectId || !memberUserId) return
    setSaving(true)
    setError('')
    setStatus('')
    try {
      await addProjectMember(Number(selectedProjectId), Number(memberUserId))
      setMemberUserId('')
      setStatus('项目成员已添加。')
      setMembers(await getProjectMembers(Number(selectedProjectId)))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '添加项目成员失败。'))
    } finally {
      setSaving(false)
    }
  }

  async function removeMember(member: ProjectMember) {
    setError('')
    setStatus('')
    try {
      await removeProjectMember(Number(selectedProjectId), member.id)
      setMembers((current) => current.filter((entry) => entry.id !== member.id))
      setStatus(`已从项目移除 ${member.username}。`)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '移除项目成员失败。'))
    }
  }

  async function submitOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setStatus('')
    try {
      await createOrganization(organizationName.trim(), organizationDescription.trim())
      setOrganizationName('')
      setOrganizationDescription('')
      setStatus('组织已创建。')
      await loadProjects()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '组织创建失败。'))
    } finally {
      setSaving(false)
    }
  }

  async function submitProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSaving(true)
    setError('')
    setStatus('')
    try {
      await createProject({
        name: projectName.trim(),
        description: projectDescription.trim(),
        organization_id: Number(organizationId),
      })
      setProjectName('')
      setProjectDescription('')
      setStatus('项目已创建。')
      await loadProjects()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '项目创建失败。'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="ORGANIZATION & PROJECTS"
        title="组织与项目"
        description="按组织 → 项目 → 数据集 → 任务管理标注工作；项目归属会随数据集传递到任务。"
      />
      {canManageProjects && <div className="platform-form-grid">
        <form className="platform-form-card" onSubmit={(event) => void submitOrganization(event)}>
          <h2>创建组织</h2>
          <label>
            组织名称
            <input maxLength={191} onChange={(event) => setOrganizationName(event.target.value)} required value={organizationName} />
          </label>
          <label>
            说明
            <textarea maxLength={2000} onChange={(event) => setOrganizationDescription(event.target.value)} rows={3} value={organizationDescription} />
          </label>
          <button className="welcome-action" disabled={saving} type="submit">创建组织</button>
        </form>
        <form className="platform-form-card" onSubmit={(event) => void submitProject(event)}>
          <h2>创建项目</h2>
          <label>
            所属组织
            <select onChange={(event) => setOrganizationId(event.target.value)} required value={organizationId}>
              {organizations.map((organization) => (
                <option key={organization.id} value={organization.id}>{organization.name}</option>
              ))}
            </select>
          </label>
          <label>
            项目名称
            <input maxLength={191} onChange={(event) => setProjectName(event.target.value)} required value={projectName} />
          </label>
          <label>
            说明
            <textarea maxLength={2000} onChange={(event) => setProjectDescription(event.target.value)} rows={3} value={projectDescription} />
          </label>
          <button className="welcome-action" disabled={saving || organizations.length === 0} type="submit">创建项目</button>
        </form>
      </div>}
      {error && <p className="platform-error" role="alert">{error}</p>}
      {status && <p className="platform-success" role="status">{status}</p>}
      <section className="platform-table-card">
        <div className="section-title-row">
          <div><h2>项目成员</h2><p>成员仅能访问已加入项目的数据集和任务。</p></div>
          <label>
            当前项目
            <select onChange={(event) => setSelectedProjectId(event.target.value)} value={selectedProjectId}>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>{project.organization_name} / {project.name}</option>
              ))}
            </select>
          </label>
        </div>
        {canManageProjects && selectedProjectId && (
          <form className="platform-inline-form" onSubmit={(event) => void addMember(event)}>
            <label>
              添加用户
              <select onChange={(event) => setMemberUserId(event.target.value)} required value={memberUserId}>
                <option value="">选择用户</option>
                {users
                  .filter((user) => !members.some((member) => member.id === user.id))
                  .map((user) => (
                    <option key={user.id} value={user.id}>{user.username}（{user.role}）</option>
                  ))}
              </select>
            </label>
            <button className="welcome-action" disabled={saving || !memberUserId} type="submit">添加成员</button>
          </form>
        )}
        {members.length === 0 ? (
          <p className="data-empty">当前项目暂无显式成员。全局管理员仍可跨项目管理。</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th scope="col">账号</th><th scope="col">角色</th><th scope="col">添加人</th><th scope="col">操作</th></tr></thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td>{member.username}</td>
                    <td>{member.role}</td>
                    <td>{member.added_by}</td>
                    <td>
                      {canManageProjects ? (
                        <button className="text-link" onClick={() => void removeMember(member)} type="button">移除</button>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="platform-table-card">
        <div className="section-title-row">
          <div><h2>项目列表</h2><p>{projects.length} 个项目</p></div>
          <button className="platform-secondary-button" onClick={() => void loadProjects()} type="button">刷新</button>
        </div>
        {loading ? (
          <p className="api-message" role="status">正在加载项目…</p>
        ) : projects.length === 0 ? (
          <p className="data-empty">暂无项目。</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead><tr><th scope="col">组织</th><th scope="col">项目</th><th scope="col">说明</th></tr></thead>
              <tbody>
                {projects.map((project) => (
                  <tr key={project.id}>
                    <td>{project.organization_name}</td>
                    <td>{project.name}</td>
                    <td>{project.description || '—'}</td>
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
