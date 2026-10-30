import { useCallback, useEffect, useState } from 'react'
import {
  getQualityCheck,
  getReviewItems,
  reviewDataItem,
  type ReviewItem,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function QualityReviewPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [statusFilter, setStatusFilter] = useState<'pending' | 'approved' | 'returned'>('pending')
  const [result, setResult] = useState<ReviewItem>({ items: [], total: 0 })
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [qualityChecks, setQualityChecks] = useState<Record<string, string[]>>({})
  const [checkingItem, setCheckingItem] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  const loadReviews = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setResult(await getReviewItems(statusFilter))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '审核数据加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [onSessionExpired, statusFilter])

  useEffect(() => {
    void loadReviews()
  }, [loadReviews])

  async function decide(itemId: string, decision: 'approved' | 'returned') {
    setError('')
    setMessage('')
    try {
      await reviewDataItem(itemId, decision, notes[itemId] ?? '')
      setMessage(decision === 'approved' ? '审核通过。' : '已退回标注修改。')
      await loadReviews()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '审核操作失败。'))
    }
  }

  async function runQualityCheck(itemId: string) {
    setCheckingItem(itemId)
    setError('')
    try {
      const result = await getQualityCheck(itemId)
      setQualityChecks((current) => ({ ...current, [itemId]: result.warnings }))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '自动质检失败。'))
    } finally {
      setCheckingItem('')
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="QUALITY REVIEW"
        title="质量审核"
        description="检查已提交的标注，记录审核意见；退回时必须说明修改原因。"
      />
      <div className="data-list-toolbar">
        <label htmlFor="review-status">审核状态</label>
        <select
          id="review-status"
          onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
          value={statusFilter}
        >
          <option value="pending">待审核</option>
          <option value="approved">已通过</option>
          <option value="returned">已退回</option>
        </select>
        <span>{result.total} 条</span>
      </div>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {message && <p className="platform-success" role="status">{message}</p>}
      {loading ? (
        <p className="api-message" role="status">正在加载审核记录…</p>
      ) : result.items.length === 0 ? (
        <p className="data-empty">当前筛选下暂无记录。</p>
      ) : (
        <div className="platform-review-list">
          {result.items.map((item) => (
            <article className="platform-review-card" key={item.id}>
              <div className="annotation-section-heading">
                <strong>数据 #{item.id}</strong>
                <span>{item.label ?? '未标注'} · {item.labeled_by ?? '—'}</span>
              </div>
              <blockquote className="annotation-content">{item.content}</blockquote>
              <button
                className="platform-secondary-button platform-check-button"
                disabled={checkingItem === item.id}
                onClick={() => void runQualityCheck(item.id)}
                type="button"
              >
                {checkingItem === item.id ? '检查中…' : '自动质检'}
              </button>
              {qualityChecks[item.id] && (
                <ul className={`platform-quality-result${qualityChecks[item.id].length === 0 ? ' is-passed' : ''}`}>
                  {qualityChecks[item.id].length === 0
                    ? <li>未发现基础规则问题。</li>
                    : qualityChecks[item.id].map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              )}
              <textarea
                aria-label={`数据 ${item.id} 的审核意见`}
                maxLength={1000}
                onChange={(event) => setNotes((current) => ({ ...current, [item.id]: event.target.value }))}
                placeholder="审核意见（退回时必填）"
                rows={2}
                value={notes[item.id] ?? ''}
              />
              {statusFilter === 'pending' && (
                <div className="annotation-action-row">
                  <button className="welcome-action" onClick={() => void decide(item.id, 'approved')} type="button">审核通过</button>
                  <button className="annotation-issue-toggle" disabled={!(notes[item.id] ?? '').trim()} onClick={() => void decide(item.id, 'returned')} type="button">退回修改</button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </>
  )
}
