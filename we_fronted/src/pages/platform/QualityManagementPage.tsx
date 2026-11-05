import { useCallback, useEffect, useState } from 'react'
import {
  getAnnotationIssues,
  getAIEvaluation,
  getQualityTrends,
  getQualityRules,
  getReviewItems,
  saveQualityRules,
  updateAnnotationIssue,
  type AnnotationIssue,
  type AIEvaluationSummary,
  type DataItem,
  type QualityTrend,
  type QualityRule,
  type ReviewItem,
} from '../../api'
import { navigateTo } from '../../routing'
import { formatDate } from '../../dateFormat'
import { handlePageError } from '../pageErrors'
import { PageTitle } from './PlatformShared'

type ReviewStatus = 'pending' | 'approved' | 'returned'
type ReviewSummary = Record<ReviewStatus, ReviewItem>

const EMPTY_REVIEW: ReviewItem = { items: [], total: 0, page: 1, page_size: 20 }

const RULE_DESCRIPTIONS: Record<QualityRule['key'], string> = {
  empty_content: '标记数据内容为空的记录。',
  min_length: '提示可能不完整或无效的过短文本。',
  missing_label: '检查记录是否已经设置有效标签。',
  missing_annotator: '确保已标注记录可以追溯到标注人员。',
  duplicate_content: '查找同一数据集中的相同文本，辅助发现重复记录。',
}

function getField(item: DataItem, field: string): string {
  const value = item.fields[field]
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '—'
}

export function QualityManagementPage({
  onSessionExpired,
  role,
  route,
}: {
  onSessionExpired: () => void
  role: string
  route: string
}) {
  const [summary, setSummary] = useState<ReviewSummary>({
    pending: EMPTY_REVIEW,
    approved: EMPTY_REVIEW,
    returned: EMPTY_REVIEW,
  })
  const [aiEvaluation, setAiEvaluation] = useState<AIEvaluationSummary>({
    evaluated_count: 0,
    accepted_count: 0,
    acceptance_rate: 0,
    by_model: [],
  })
  const [qualityTrends, setQualityTrends] = useState<QualityTrend[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [selectedTab, setSelectedTab] = useState<'rules' | 'report' | 'issues'>(
    route === '/operations/security' ? 'rules' : 'report',
  )
  const [rules, setRules] = useState<QualityRule[]>([])
  const [issues, setIssues] = useState<AnnotationIssue[]>([])
  const [issueStatus, setIssueStatus] = useState('')
  const [isSavingRules, setIsSavingRules] = useState(false)
  const [updatingIssueId, setUpdatingIssueId] = useState<number | null>(null)
  const [issueResolutions, setIssueResolutions] = useState<Record<number, string>>({})
  const [issueStatuses, setIssueStatuses] = useState<Record<number, AnnotationIssue['status']>>({})
  const canManageRules = role === '超级管理员' || role === '项目管理员'

  const loadReport = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [pending, approved, returned, evaluation, trends] = await Promise.all([
        getReviewItems('pending', { pageSize: 1 }),
        getReviewItems('approved', { pageSize: 100 }),
        getReviewItems('returned', { pageSize: 100 }),
        getAIEvaluation(),
        getQualityTrends(),
      ])
      setSummary({ pending, approved, returned })
      setAiEvaluation(evaluation)
      setQualityTrends(trends)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '质检报告加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void loadReport()
  }, [loadReport])

  const loadRules = useCallback(async () => {
    try {
      setRules(await getQualityRules())
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '质检规则加载失败。'))
    }
  }, [onSessionExpired])

  const loadIssues = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await getAnnotationIssues({
        page: 1,
        pageSize: 100,
        status: issueStatus as AnnotationIssue['status'] || undefined,
      })
      setIssues(result.items)
      setIssueResolutions(Object.fromEntries(
        result.items.map((issue) => [issue.id, issue.resolution]),
      ))
      setIssueStatuses(Object.fromEntries(
        result.items.map((issue) => [issue.id, issue.status]),
      ))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '异常反馈加载失败。'))
    } finally {
      setLoading(false)
    }
  }, [issueStatus, onSessionExpired])

  useEffect(() => {
    if (selectedTab === 'rules') void loadRules()
    if (selectedTab === 'issues') void loadIssues()
  }, [loadIssues, loadRules, selectedTab])

  async function saveRules() {
    setIsSavingRules(true)
    setError('')
    try {
      setRules(await saveQualityRules(rules))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '质检规则保存失败。'))
    } finally {
      setIsSavingRules(false)
    }
  }

  async function updateIssue(
    issue: AnnotationIssue,
    changes: Parameters<typeof updateAnnotationIssue>[1],
  ) {
    setUpdatingIssueId(issue.id)
    setError('')
    try {
      await updateAnnotationIssue(issue.id, changes)
      await loadIssues()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '异常反馈更新失败。'))
    } finally {
      setUpdatingIssueId(null)
    }
  }

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
          onClick={() => {
            setSelectedTab('rules')
            navigateTo('/operations/security')
          }}
          role="tab"
          type="button"
        >
          质检规则
        </button>
        <button
          aria-selected={selectedTab === 'report'}
          className={`platform-quality-tab${selectedTab === 'report' ? ' is-active' : ''}`}
          onClick={() => {
            setSelectedTab('report')
            navigateTo('/operations/complaints')
          }}
          role="tab"
          type="button"
        >
          质检报告
        </button>
        <button
          aria-selected={selectedTab === 'issues'}
          className={`platform-quality-tab${selectedTab === 'issues' ? ' is-active' : ''}`}
          onClick={() => setSelectedTab('issues')}
          role="tab"
          type="button"
        >
          异常闭环
        </button>
      </div>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {selectedTab === 'rules' ? (
        <section aria-label="当前质检规则" className="platform-table-card">
          <div className="section-title-row">
            <div>
              <h2>自动质检规则</h2>
              <p>{rules.length} 项规则；调整后会应用于后续按需质检。</p>
            </div>
            {canManageRules && (
              <button
                className="welcome-action"
                disabled={isSavingRules || rules.length === 0}
                onClick={() => void saveRules()}
                type="button"
              >
                {isSavingRules ? '保存中…' : '保存规则'}
              </button>
            )}
          </div>
          <div className="data-table-wrap">
            <table className="data-table quality-rules-table">
              <thead>
                <tr>
                  <th scope="col">规则</th>
                  <th scope="col">说明</th>
                  <th scope="col">启用</th>
                  <th scope="col">阈值</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.key}>
                    <td>{rule.name}</td>
                    <td>{RULE_DESCRIPTIONS[rule.key]}</td>
                    <td>
                      <input
                        aria-label={`启用${rule.name}`}
                        checked={rule.enabled}
                        disabled={!canManageRules || isSavingRules}
                        onChange={(event) => setRules((current) =>
                          current.map((entry) => entry.key === rule.key
                            ? { ...entry, enabled: event.target.checked }
                            : entry),
                        )}
                        type="checkbox"
                      />
                    </td>
                    <td>
                      {rule.key === 'min_length' ? (
                        <input
                          aria-label={`${rule.name}阈值`}
                          disabled={!canManageRules || isSavingRules}
                          max={1000}
                          min={1}
                          onChange={(event) => setRules((current) =>
                            current.map((entry) => entry.key === rule.key
                              ? { ...entry, threshold: Number(event.target.value) }
                              : entry),
                          )}
                          type="number"
                          value={rule.threshold ?? 3}
                        />
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="platform-form-hint">
            最小内容长度仅对非空文本生效。审核员可查看规则，平台/项目管理员可配置。
          </p>
        </section>
      ) : selectedTab === 'issues' ? (
        <section className="platform-table-card">
          <div className="section-title-row">
            <div>
              <h2>异常反馈处理</h2>
              <p>跟进数据反馈状态并记录处理结论；最多显示 100 条。</p>
            </div>
            <select
              aria-label="异常状态筛选"
              onChange={(event) => setIssueStatus(event.target.value)}
              value={issueStatus}
            >
              <option value="">全部状态</option>
              <option value="待处理">待处理</option>
              <option value="处理中">处理中</option>
              <option value="已解决">已解决</option>
              <option value="已关闭">已关闭</option>
            </select>
          </div>
          {loading ? (
            <p className="api-message" role="status">正在加载异常反馈…</p>
          ) : issues.length === 0 ? (
            <p className="data-empty">暂无异常反馈。</p>
          ) : (
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">数据</th>
                    <th scope="col">类型 / 说明</th>
                    <th scope="col">提交人</th>
                    <th scope="col">状态</th>
                    <th scope="col">处理说明</th>
                    <th scope="col">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {issues.map((issue) => (
                    <tr key={issue.id}>
                      <td>
                        <button className="text-link" onClick={() => navigateTo(`/data/detail/${encodeURIComponent(issue.item_id)}`)} type="button">
                          {issue.item_id}
                        </button>
                      </td>
                      <td>{issue.issue_type}：{issue.description}</td>
                      <td>{issue.reported_by}</td>
                      <td>
                        <select
                          aria-label={`异常 ${issue.id} 状态`}
                          disabled={updatingIssueId === issue.id}
                          onChange={(event) => setIssueStatuses((current) => ({
                            ...current,
                            [issue.id]: event.target.value as AnnotationIssue['status'],
                          }))}
                          value={issueStatuses[issue.id] ?? issue.status}
                        >
                          {(['待处理', '处理中', '已解决', '已关闭'] as const).map((value) => (
                            <option key={value} value={value}>{value}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          aria-label={`异常 ${issue.id} 处理说明`}
                          maxLength={1000}
                          onChange={(event) => setIssueResolutions((current) => ({
                            ...current,
                            [issue.id]: event.target.value,
                          }))}
                          value={issueResolutions[issue.id] ?? ''}
                        />
                      </td>
                      <td>
                        <button
                          className="text-link"
                          disabled={updatingIssueId === issue.id}
                          onClick={() => void updateIssue(issue, {
                            status: issueStatuses[issue.id] ?? issue.status,
                            resolution: issueResolutions[issue.id] ?? '',
                          })}
                          type="button"
                        >
                          保存处理说明
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
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
                <article>
                  <span>AI 建议采纳</span>
                  <strong>{aiEvaluation.accepted_count} / {aiEvaluation.evaluated_count}</strong>
                </article>
                <article>
                  <span>AI 采纳率</span>
                  <strong>{(aiEvaluation.acceptance_rate * 100).toFixed(1)}%</strong>
                </article>
              </div>
              <section className="platform-table-card">
                <div className="section-title-row">
                  <div>
                    <h2>月度审核趋势</h2>
                    <p>按审核完成时间统计通过与退回记录。</p>
                  </div>
                </div>
                {qualityTrends.length === 0 ? (
                  <p className="data-empty">暂无月度审核数据。</p>
                ) : (
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">月份</th>
                          <th scope="col">审核数</th>
                          <th scope="col">通过</th>
                          <th scope="col">退回</th>
                        </tr>
                      </thead>
                      <tbody>
                        {qualityTrends.map((trend) => (
                          <tr key={trend.month}>
                            <td>{trend.month}</td>
                            <td>{trend.total}</td>
                            <td>{trend.approved}</td>
                            <td>{trend.returned}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
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
