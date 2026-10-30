import { useEffect, useState } from 'react'
import {
  getPlatformStatistics,
  getProjects,
  type ProjectRecord,
  type PlatformStatistics,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function StatisticsPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [stats, setStats] = useState<PlatformStatistics | null>(null)
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [projectId, setProjectId] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    void getProjects(controller.signal)
      .then(setProjects)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(handlePageError(cause, onSessionExpired, '项目列表加载失败。'))
      })
    return () => controller.abort()
  }, [onSessionExpired])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    void getPlatformStatistics(
      controller.signal,
      projectId ? Number(projectId) : undefined,
    )
      .then(setStats)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(handlePageError(cause, onSessionExpired, '统计数据加载失败。'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [onSessionExpired, projectId])

  return (
    <>
      <PageTitle
        eyebrow="STATISTICS"
        title="统计分析"
        description="按标注结果、人员和审核状态汇总当前 Elastic 数据索引中的实时数据。"
      />
      <div className="data-list-toolbar">
        <label htmlFor="statistics-project">项目范围</label>
        <select
          id="statistics-project"
          onChange={(event) => setProjectId(event.target.value)}
          value={projectId}
        >
          <option value="">全部项目</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>{project.organization_name} / {project.name}</option>
          ))}
        </select>
      </div>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {loading ? (
        <p className="api-message" role="status">正在汇总数据…</p>
      ) : stats && (
        <>
          <div className="data-summary platform-stats-summary">
            <div><span>数据总量</span><strong>{stats.total.toLocaleString()}</strong></div>
            <div><span>已标注</span><strong>{stats.labeled.toLocaleString()}</strong></div>
            <div><span>待标注</span><strong>{stats.unlabeled.toLocaleString()}</strong></div>
            <div><span>完成率</span><strong>{stats.completion_rate}%</strong></div>
            <div><span>已审核</span><strong>{stats.reviewed.toLocaleString()}</strong></div>
            <div><span>已逾期任务</span><strong>{stats.overdue_tasks.toLocaleString()}</strong></div>
          </div>
          <section className="platform-form-grid platform-stat-tables">
            <div className="platform-table-card">
              <h2>标签分布</h2>
              {stats.labels.length === 0 ? <p className="data-empty">暂无标注结果。</p> : stats.labels.map((row) => (
                <div className="platform-stat-row" key={row.name}>
                  <span>{row.name}</span><strong>{row.count}</strong>
                  <progress max={Math.max(stats.labeled, 1)} value={row.count} />
                </div>
              ))}
            </div>
            <div className="platform-table-card">
              <h2>人员工作量</h2>
              {stats.annotators.length === 0 ? <p className="data-empty">暂无人员统计。</p> : stats.annotators.map((row) => (
                <div className="platform-stat-row" key={row.name}>
                  <span>{row.name}</span><strong>{row.count} 条</strong>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  )
}
