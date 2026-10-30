import { useEffect, useState } from 'react'
import {
  ApiError,
  getDataItem,
  type DataItem,
} from '../../api'
import { formatDate } from './dataItemsLogic'
import { DataPageHeading } from './DataItemsShared'

export function DataDetailPage({
  itemId,
  onSessionExpired,
}: {
  itemId: string
  onSessionExpired: () => void
}) {
  const [item, setItem] = useState<DataItem | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void getDataItem(itemId, controller.signal)
      .then(setItem)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && cause.status === 401) {
          onSessionExpired()
          return
        }
        setError(cause instanceof Error ? cause.message : '详情加载失败。')
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [itemId, loadAttempt, onSessionExpired])

  function retry() {
    setIsLoading(true)
    setError('')
    setLoadAttempt((attempt) => attempt + 1)
  }

  return (
    <>
      <DataPageHeading
        eyebrow="DATA DETAIL"
        title="数据详情"
        description={`查看数据记录 #${itemId} 的内容和标注信息。`}
      />
      {isLoading ? (
        <p className="api-message" role="status">正在加载数据详情…</p>
      ) : error ? (
        <div className="api-error" role="alert">
          <p>详情加载失败：{error}</p>
          <button className="welcome-action" onClick={retry} type="button">
            重试
          </button>
        </div>
      ) : item ? (
        <section aria-label="数据详情" className="data-detail-card">
          <dl>
            <div>
              <dt>数据编号</dt>
              <dd>{item.id}</dd>
            </div>
            <div className="data-detail-content">
              <dt>数据内容</dt>
              <dd>{item.content || '（无内容）'}</dd>
            </div>
            <div>
              <dt>标注结果</dt>
              <dd>{item.label ?? '未标注'}</dd>
            </div>
            <div>
              <dt>标注人</dt>
              <dd>{item.labeled_by ?? '—'}</dd>
            </div>
            <div>
              <dt>创建时间</dt>
              <dd>{formatDate(item.inserted_at)}</dd>
            </div>
            <div>
              <dt>标注时间</dt>
              <dd>{formatDate(item.labeled_at)}</dd>
            </div>
          </dl>
          <div className="data-detail-fields">
            <h2>完整数据字段</h2>
            <pre>{JSON.stringify(item.fields, null, 2)}</pre>
          </div>
        </section>
      ) : null}
    </>
  )
}
