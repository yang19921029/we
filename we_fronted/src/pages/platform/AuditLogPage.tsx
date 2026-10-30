import { useEffect, useState } from 'react'
import {
  getAuditLogs,
  type AuditLog,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function AuditLogPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    const controller = new AbortController()
    void getAuditLogs(controller.signal)
      .then((result) => {
        setLogs(result.items)
        setTotal(result.total)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(handlePageError(cause, onSessionExpired, '操作日志加载失败。'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [onSessionExpired])
  return (
    <>
      <PageTitle
        eyebrow="AUDIT LOG"
        title="操作日志"
        description={`保留数据集、任务、标签体系及用户权限变更记录，共 ${total} 条。`}
      />
      {error && <p className="platform-error" role="alert">{error}</p>}
      {loading ? (
        <p className="api-message" role="status">正在加载操作日志…</p>
      ) : logs.length === 0 ? (
        <p className="data-empty">暂无操作日志。</p>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">时间</th>
                <th scope="col">操作人</th>
                <th scope="col">操作</th>
                <th scope="col">对象</th>
                <th scope="col">详情</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => (
                <tr key={log.id}>
                  <td>{String(log.created_at).slice(0, 19)}</td>
                  <td>{log.actor}</td>
                  <td>{log.action}</td>
                  <td>{log.entity_type} #{log.entity_id}</td>
                  <td>{JSON.stringify(log.details)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
