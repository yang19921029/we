import { useCallback, useEffect, useState } from 'react'
import { getReviewItems, type DataItem, type ReviewItem } from '../../api'
import { navigateTo } from '../../routing'
import { formatDate } from '../../dateFormat'
import { handlePageError } from '../pageErrors'
import { PageTitle } from './PlatformShared'

type ReviewStatus = 'pending' | 'approved' | 'returned'
type ReviewSummary = Record<ReviewStatus, ReviewItem>

const EMPTY_REVIEW: ReviewItem = { items: [], total: 0, page: 1, page_size: 20 }

const QUALITY_RULES = [
  {
    name: '内容完整性',
    description: '标记数据内容为空的记录。',
    criterion: '内容为空或仅包含空白字符',
  },
  {
    name: '内容长度',
    description: '提示可能不完整或无效的过短文本。',
    criterion: '有效内容少于 3 个字符',
  },
  {
    name: '标注结果',
    description: '检查记录是否已经设置有效标签。',
    criterion: '标签缺失或为空',
  },
  {
    name: '标注人信息',
    description: '确保已标注记录可以追溯到标注人员。',
    criterion: '存在标签但缺少标注人',
  },
  {
    name: '数据集内重复内容',
    description: '查找同一数据集中的相同文本，辅助发现重复记录。',
    criterion: '当前数据集存在内容相同的其他记录',
  },
]

function getField(item: DataItem, field: string): string {
  const value = item.fields[field]
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '—'
}

export function QualityManagementPage({
  onSessionExpired,
  route,
}: {
  onSessionExpired: () => void
  route: string
}) {
  const [summary, setSummary] = useState<ReviewSummary>({
    pending: EMPTY_REVIEW,
    approved: EMPTY_REVIEW,
    returned: EMPTY_REVIEW,
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const selectedTab = route === '/operations/security' ? 'rules' : 'report'

  const loadReport = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [pending, approved, returned] = await Promise.all([
        getReviewItems('pending', { pageSize: 1 }),
        getReviewItems('approved', { pageSize: 100 }),
        getReviewItems('returned', { pageSize: 100 }),
      ])
      setSummary({ pending, approved, returned })
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '质检报告加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void loadReport()
  }, [loadReport])

  const reviewedCount = summary.approved.total + summary.returned.total
  const passRate = reviewedCount
    ? Math.round((summary.approved.total / reviewedCount) * 1000) / 10
    : 0
  const recentReviews = [...summary.approved.items, ...summary.returned.items]
    .sort((left, right) => {
      const leftTime = Date.parse(getField(left, 'reviewed_at'))
      const rightTime = Date.parse(getField(right, 'reviewed_at'))
      return (Number.isFinite(rightTime) ? rightTime : 0)
        - (Number.isFinite(leftTime) ? leftTime : 0)
    })
    .slice(0, 100)

  return (
    <>
      <PageTitle
        eyebrow="QUALITY MANAGEMENT"
        title="质检规则与报告"
        description="查看当前执行的自动质检规则，汇总审核结果并追踪退回记录。"
      />
      <div aria-label="质检规则与报告" className="platform-quality-tabs" role="tablist">
        <button
          aria-selected={selectedTab === 'rules'}
          className={`platform-quality-tab${selectedTab === 'rules' ? ' is-active' : ''}`}
          onClick={() => navigateTo('/operations/security')}
          role="tab"
          type="button"
        >
          质检规则
        </button>
        <button
          aria-selected={selectedTab === 'report'}
          className={`platform-quality-tab${selectedTab === 'report' ? ' is-active' : ''}`}
          onClick={() => navigateTo('/operations/complaints')}
          role="tab"
          type="button"
        >
          质检报告
        </button>
      </div>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {selectedTab === 'rules' ? (
        <section aria-label="当前质检规则" className="platform-table-card">
          <div className="section-title-row">
            <div>
              <h2>自动质检规则</h2>
              <p>{QUALITY_RULES.length} 项系统规则；每项检查在审核页面按需执行。</p>
            </div>
          </div>
          <div className="data-table-wrap">
            <table className="data-table quality-rules-table">
              <thead>
                <tr>
                  <th scope="col">规则</th>
                  <th scope="col">检查条件</th>
                  <th scope="col">说明</th>
                </tr>
              </thead>
              <tbody>
                {QUALITY_RULES.map((rule) => (
                  <tr key={rule.name}>
                    <td>{rule.name}</td>
                    <td>{rule.criterion}</td>
                    <td>{rule.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="platform-form-hint">
            规则目前由系统固定执行，自动质检结果会显示在“质检任务”记录中。
          </p>
        </section>
      ) : (
        <>
          <div className="section-title-row quality-report-heading">
            <div>
              <h2>审核概览</h2>
              <p>按当前账号可访问范围内记录的最终审核状态汇总。</p>
            </div>
            <button
              className="platform-secondary-button"
              disabled={loading}
              onClick={() => void loadReport()}
              type="button"
            >
              刷新报告
            </button>
          </div>
          {loading ? (
            <p className="api-message" role="status">正在生成质检报告…</p>
          ) : (
            <>
              <div className="platform-quality-metrics">
                <article>
                  <span>待审核</span>
                  <strong>{summary.pending.total}</strong>
                </article>
                <article>
                  <span>已完成审核</span>
                  <strong>{reviewedCount}</strong>
                </article>
                <article>
                  <span>审核通过</span>
                  <strong>{summary.approved.total}</strong>
                </article>
                <article>
                  <span>退回修改</span>
                  <strong>{summary.returned.total}</strong>
                </article>
                <article>
                  <span>通过率</span>
                  <strong>{passRate}%</strong>
                </article>
              </div>
              <section className="platform-table-card">
                <div className="section-title-row">
                  <div>
                    <h2>已完成审核记录</h2>
                    <p>最多显示 100 条当前查询到的已完成审核记录。</p>
                  </div>
                </div>
                {recentReviews.length === 0 ? (
                  <p className="data-empty">暂无已完成的审核记录。</p>
                ) : (
                  <div className="data-table-wrap">
                    <table className="data-table quality-report-table">
                      <thead>
                        <tr>
                          <th scope="col">数据编号</th>
                          <th scope="col">数据集</th>
                          <th scope="col">标注结果</th>
                          <th scope="col">审核结果</th>
                          <th scope="col">审核人</th>
                          <th scope="col">审核时间</th>
                          <th scope="col">审核意见</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentReviews.map((item) => (
                          <tr key={item.id}>
                            <td>{item.id}</td>
                            <td>{getField(item, 'dataset_id')}</td>
                            <td>{item.label ?? '—'}</td>
                            <td>
                              {getField(item, 'review_status') === 'approved'
                                ? '通过'
                                : '退回修改'}
                            </td>
                            <td>{getField(item, 'reviewed_by')}</td>
                            <td>{formatDate(getField(item, 'reviewed_at'))}</td>
                            <td>{getField(item, 'review_note')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  )
}
