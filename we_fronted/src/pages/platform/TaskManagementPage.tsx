import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  autoAssignAnnotationTask,
  createAnnotationTask,
  getAnnotationTasks,
  getDatasets,
  getLabelSchemas,
  getProjectMembers,
  updateAnnotationTask,
  type AnnotationTask,
  type DatasetRecord,
  type ProjectMember,
  type LabelSchema,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function TaskManagementPage({
  onSessionExpired,
  onOpenTask,
  username,
}: {
  onSessionExpired: () => void
  onOpenTask: (taskId: number) => void
  username: string
}) {
  const [tasks, setTasks] = useState<AnnotationTask[]>([])
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [schemas, setSchemas] = useState<LabelSchema[]>([])
  const [membersByProject, setMembersByProject] = useState<Record<number, ProjectMember[]>>({})
  const [name, setName] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [schemaId, setSchemaId] = useState('')
  const [assignee, setAssignee] = useState('')
  const [priority, setPriority] = useState<AnnotationTask['priority']>('中')
  const [deadline, setDeadline] = useState('')
  const [instructions, setInstructions] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [isLoading, setIsLoading] = useState(true)

  const loadPageData = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const [nextTasks, nextDatasets, nextSchemas] = await Promise.all([
        getAnnotationTasks(),
        getDatasets(),
        getLabelSchemas(),
      ])
      const projectIds = [...new Set(nextDatasets.map((dataset) => dataset.project_id))]
      const memberLists = await Promise.all(
        projectIds.map((id) => getProjectMembers(id)),
      )
      const nextMembersByProject = Object.fromEntries(
        projectIds.map((id, index) => [id, memberLists[index]]),
      )
      setTasks(nextTasks)
      setDatasets(nextDatasets)
      setSchemas(nextSchemas)
      setMembersByProject(nextMembersByProject)
      setDatasetId((current) => current || String(nextDatasets[0]?.id ?? ''))
      setSchemaId((current) => current || String(nextSchemas[0]?.id ?? ''))
      setAssignee(
        (current) =>
          current ||
          nextMembersByProject[nextDatasets[0]?.project_id]?.find((user) => user.role === '标注员')?.username ||
          nextMembersByProject[nextDatasets[0]?.project_id]?.[0]?.username ||
          '',
      )
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '任务数据加载失败。'))
    } finally {
      setIsLoading(false)
    }
  }, [onSessionExpired])
  const selectedDataset = datasets.find((dataset) => String(dataset.id) === datasetId)
  const assigneeMembers = selectedDataset
    ? membersByProject[selectedDataset.project_id] ?? []
    : []

  useEffect(() => {
    void loadPageData()
  }, [loadPageData])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    setError('')
    setStatus('')
    try {
      await createAnnotationTask({
        name: name.trim(),
        dataset_id: Number(datasetId),
        label_schema_id: Number(schemaId),
        assignee: assignee.trim(),
        priority,
        deadline,
        instructions: instructions.trim(),
      })
      setName('')
      setInstructions('')
      setStatus('标注任务已创建。')
      await loadPageData()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '任务创建失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  async function changeStatus(task: AnnotationTask, nextStatus: string) {
    setError('')
    try {
      await updateAnnotationTask(task.id, { status: nextStatus })
      setTasks((current) =>
        current.map((entry) =>
          entry.id === task.id ? { ...entry, status: nextStatus } : entry,
        ),
      )
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '任务状态更新失败。'))
    }
  }

  async function autoAssign(task: AnnotationTask) {
    setError('')
    try {
      const result = await autoAssignAnnotationTask(task.id)
      setTasks((current) =>
        current.map((entry) =>
          entry.id === task.id
            ? { ...entry, assignee: result.assignee, status: '待标注' }
            : entry,
        ),
      )
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '自动分配失败。'))
    }
  }

  async function changeAssignee(task: AnnotationTask, assignee: string) {
    setError('')
    try {
      await updateAnnotationTask(task.id, { assignee })
      setTasks((current) =>
        current.map((entry) =>
          entry.id === task.id ? { ...entry, assignee } : entry,
        ),
      )
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '任务分配失败。'))
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="TASK MANAGEMENT"
        title="标注任务"
        description="选择数据集和标签规范创建任务，设置负责人、优先级及截止时间并跟踪任务状态。"
      />
      <form className="platform-form-card task-create-form" onSubmit={(event) => void handleCreate(event)}>
        <h2>创建任务</h2>
        <div className="platform-form-grid">
          <label>
            任务名称
            <input maxLength={191} onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            数据集
            <select onChange={(event) => setDatasetId(event.target.value)} required value={datasetId}>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.project_name} / {dataset.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            标签体系
            <select onChange={(event) => setSchemaId(event.target.value)} required value={schemaId}>
              {schemas.map((schema) => (
                <option key={schema.id} value={schema.id}>{schema.name}（v{schema.version}）</option>
              ))}
            </select>
          </label>
          <label>
            负责人账号
            <select onChange={(event) => setAssignee(event.target.value)} required value={assignee}>
              {assigneeMembers.map((user) => (
                <option key={user.id} value={user.username}>{user.username}（{user.role}）</option>
              ))}
            </select>
          </label>
          <label>
            优先级
            <select onChange={(event) => setPriority(event.target.value as AnnotationTask['priority'])} value={priority}>
              <option value="高">高</option>
              <option value="中">中</option>
              <option value="低">低</option>
            </select>
          </label>
          <label>
            截止时间
            <input onChange={(event) => setDeadline(event.target.value)} type="datetime-local" value={deadline} />
          </label>
          <label className="platform-field-full">
            标注说明
            <textarea maxLength={2000} onChange={(event) => setInstructions(event.target.value)} rows={3} value={instructions} />
          </label>
        </div>
        <button className="welcome-action" disabled={isSaving || datasets.length === 0 || schemas.length === 0 || assigneeMembers.length === 0} type="submit">
          {isSaving ? '创建中…' : '创建任务'}
        </button>
      </form>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {status && <p className="platform-success" role="status">{status}</p>}
      <section className="platform-table-card">
        <div className="section-title-row">
          <div>
            <h2>任务列表</h2>
            <p>{tasks.length} 个任务</p>
          </div>
          <button className="platform-secondary-button" onClick={() => void loadPageData()} type="button">刷新</button>
        </div>
        {isLoading ? (
          <p className="api-message" role="status">正在加载任务…</p>
        ) : tasks.length === 0 ? (
          <p className="data-empty">暂无标注任务。</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">任务</th>
                  <th scope="col">项目</th>
                  <th scope="col">数据集 / 标签</th>
                  <th scope="col">负责人</th>
                  <th scope="col">优先级</th>
                  <th scope="col">进度</th>
                  <th scope="col">状态</th>
                  <th scope="col">截止时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id}>
                    <td>{task.name}</td>
                    <td>{task.project_name}</td>
                    <td>{task.dataset_name} / {task.label_schema_name}</td>
                    <td>
                      {(() => {
                        const taskMembers = membersByProject[task.project_id] ?? []
                        return (
                      <select
                        aria-label={`${task.name}负责人`}
                        onChange={(event) => void changeAssignee(task, event.target.value)}
                        value={task.assignee}
                      >
                        {!taskMembers.some((user) => user.username === task.assignee) && (
                          <option value={task.assignee}>{task.assignee}</option>
                        )}
                        {taskMembers.map((user) => (
                          <option key={user.id} value={user.username}>{user.username}</option>
                        ))}
                      </select>
                        )
                      })()}
                    </td>
                    <td>{task.priority}</td>
                    <td>
                      {task.labeled_items ?? 0} / {task.total_items ?? 0}
                      <progress
                        className="platform-task-progress"
                        max={Math.max(task.total_items ?? 0, 1)}
                        value={task.labeled_items ?? 0}
                      />
                    </td>
                    <td>
                      <select
                        aria-label={`${task.name}状态`}
                        onChange={(event) => void changeStatus(task, event.target.value)}
                        value={task.status}
                      >
                        {['待分配', '待标注', '标注中', '待审核', '已完成', '已退回', '已暂停'].map((value) => (
                          <option key={value} value={value}>{value}</option>
                        ))}
                      </select>
                    </td>
                    <td>{task.deadline ? String(task.deadline).slice(0, 16) : '—'}</td>
                    <td>
                      <button className="text-link" onClick={() => void autoAssign(task)} type="button">自动分配</button>
                      {task.assignee === username && (
                        <>
                          {' · '}
                          <button className="text-link" onClick={() => onOpenTask(task.id)} type="button">开始标注</button>
                        </>
                      )}
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
