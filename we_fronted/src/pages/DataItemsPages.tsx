import { useEffect, useState } from 'react'
import {
  ApiError,
  getDataItem,
  getDataItems,
  saveDataItemLabel,
  type LabelStatusFilter,
  type DataItem,
  type DataLabel,
} from '../api'

const LABEL_OPTIONS: DataLabel[] = ['正向', '中性', '负向']

const PAGE_SIZE = 20
const ANNOTATION_PAGE_SIZE = 100

function isDataLabel(label: string | null | undefined): label is DataLabel {
  return Boolean(label && LABEL_OPTIONS.includes(label as DataLabel))
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const datePrefix = /^\d{4}-\d{2}-\d{2}/.exec(value)?.[0]
  if (datePrefix) return datePrefix

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(0, 10)
}

function useDataItems(
  onSessionExpired: () => void,
  page: number,
  pageSize: number,
  labelStatus: LabelStatusFilter,
) {
  const [items, setItems] = useState<DataItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void getDataItems(page, pageSize, labelStatus, controller.signal)
      .then((result) => {
        setItems(result.items)
        setTotal(result.total)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && cause.status === 401) {
          onSessionExpired()
          return
        }
        setError(cause instanceof Error ? cause.message : '数据加载失败。')
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [labelStatus, loadAttempt, onSessionExpired, page, pageSize])

  async function saveLabel(itemId: string, label: DataLabel) {
    try {
      const result = await saveDataItemLabel(itemId, label)
      setItems((currentItems) =>
        currentItems.map((item) =>
          item.id === result.id
            ? {
                ...item,
                label: result.label,
                labeled_by: result.labeled_by,
                labeled_at: result.labeled_at,
              }
            : item,
        ),
      )
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired()
      }
      throw cause
    }
  }

  function retry() {
    setError('')
    setIsLoading(true)
    setLoadAttempt((attempt) => attempt + 1)
  }

  return { items, total, isLoading, error, retry, saveLabel }
}

function DataPageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="content-heading data-page-heading">
      <div>
        <p className="content-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="content-subtitle">{description}</p>
      </div>
    </div>
  )
}

function DataLoadState({
  isLoading,
  error,
  onRetry,
}: {
  isLoading: boolean
  error: string
  onRetry: () => void
}) {
  if (isLoading) {
    return <p className="api-message" role="status">正在加载数据…</p>
  }
  if (error) {
    return (
      <div className="api-error" role="alert">
        <p>数据加载失败：{error}</p>
        <button className="welcome-action" onClick={onRetry} type="button">
          重试
        </button>
      </div>
    )
  }
  return null
}

export function DataListPage({
  onSessionExpired,
  onOpenDetails,
}: {
  onSessionExpired: () => void
  onOpenDetails: (itemId: string) => void
}) {
  const [page, setPage] = useState(1)
  const [pageInput, setPageInput] = useState('1')
  const [labelStatus, setLabelStatus] = useState<LabelStatusFilter>('all')
  const { items, total, isLoading, error, retry } = useDataItems(
    onSessionExpired,
    page,
    PAGE_SIZE,
    labelStatus,
  )
  const labeledCount = items.filter((item) => item.label !== null).length
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  function goToPage() {
    const requestedPage = Number(pageInput)
    if (
      !Number.isInteger(requestedPage) ||
      requestedPage < 1 ||
      requestedPage > pageCount
    ) {
      return
    }
    setPage(requestedPage)
    setPageInput(String(requestedPage))
  }

  function changePage(nextPage: number) {
    setPage(nextPage)
    setPageInput(String(nextPage))
  }

  return (
    <>
      <DataPageHeading
        eyebrow="DATA OVERVIEW"
        title="数据展示列表"
        description="查看数据记录。已标注表示已有 label 标注，未标注表示尚无 label。"
      />
      <div className="data-list-toolbar">
        <label htmlFor="label-status-filter">标注状态</label>
        <select
          id="label-status-filter"
          onChange={(event) => {
            setLabelStatus(event.target.value as LabelStatusFilter)
            setPage(1)
            setPageInput('1')
          }}
          value={labelStatus}
        >
          <option value="all">全部</option>
          <option value="labeled">已标注</option>
          <option value="unlabeled">未标注</option>
          <option value="正向">正向</option>
          <option value="负向">负向</option>
          <option value="中性">中性</option>
        </select>
      </div>
      <div className="data-summary">
        <div>
          <span>数据总量</span>
          <strong>{total}</strong>
        </div>
        <div>
          <span>本页未标注</span>
          <strong>{items.length - labeledCount}</strong>
        </div>
        <div>
          <span>本页已标注</span>
          <strong>{labeledCount}</strong>
        </div>
      </div>
      <DataLoadState isLoading={isLoading} error={error} onRetry={retry} />
      {!isLoading && !error && (
        <div className="data-table-wrap">
          {items.length === 0 ? (
            <p className="data-empty">暂无数据记录。</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">编号</th>
                  <th scope="col">数据内容</th>
                  <th scope="col">创建时间</th>
                  <th scope="col">标注结果</th>
                  <th scope="col">打标时间</th>
                  <th scope="col">标注人</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>#{item.id}</td>
                    <td>{item.content}</td>
                    <td>{formatDate(item.inserted_at)}</td>
                    <td>
                      <span className={`data-status${item.label ? ' is-labeled' : ''}`}>
                        {item.label ?? '未标注'}
                      </span>
                    </td>
                    <td>{formatDate(item.labeled_at)}</td>
                    <td>{item.labeled_by ?? '—'}</td>
                    <td>
                      <button
                        className="text-link"
                        onClick={() => onOpenDetails(item.id)}
                        type="button"
                      >
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {!isLoading && !error && total > PAGE_SIZE && (
        <div className="data-pagination">
          <span>
            第 {page} / {pageCount} 页，共 {total} 条
          </span>
          <div>
            <button
              disabled={page <= 1}
              onClick={() => changePage(page - 1)}
              type="button"
            >
              上一页
            </button>
            <button
              disabled={page >= pageCount}
              onClick={() => changePage(page + 1)}
              type="button"
            >
              下一页
            </button>
            <label className="page-jump">
              <span>跳转</span>
              <input
                aria-label="跳转到指定页"
                max={pageCount}
                min={1}
                onChange={(event) => setPageInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') goToPage()
                }}
                type="number"
                value={pageInput}
              />
              <span>页</span>
            </label>
            <button
              disabled={
                !Number.isInteger(Number(pageInput)) ||
                Number(pageInput) < 1 ||
                Number(pageInput) > pageCount
              }
              onClick={goToPage}
              type="button"
            >
              跳转
            </button>
          </div>
        </div>
      )}
    </>
  )
}

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
              <dt>打标时间</dt>
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

export function DataLabelPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [page, setPage] = useState(1)
  const { items, total, isLoading, error, retry, saveLabel } = useDataItems(
    onSessionExpired,
    page,
    ANNOTATION_PAGE_SIZE,
    'all',
  )
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [chosenLabel, setChosenLabel] = useState<DataLabel | ''>('')
  const [saveError, setSaveError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const selectedItem =
    items.find((item) => item.id === selectedId) ??
    items.find((item) => item.label === null) ??
    items[0]
  const activeLabel: DataLabel | '' =
    chosenLabel ||
    (isDataLabel(selectedItem?.label) ? selectedItem.label : '')
  const pageCount = Math.max(1, Math.ceil(total / ANNOTATION_PAGE_SIZE))

  async function handleSave() {
    if (!selectedItem || !activeLabel) return
    setSaveError('')
    setSuccessMessage('')
    setIsSaving(true)
    try {
      await saveLabel(selectedItem.id, activeLabel)
      setSuccessMessage(`数据 #${selectedItem.id} 的标注已保存。`)
    } catch (cause) {
      setSaveError(cause instanceof Error ? cause.message : '保存标注失败。')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <>
      <DataPageHeading
        eyebrow="DATA ANNOTATION"
        title="数据打标"
        description="选择一条数据并设置情感分类，保存后标注结果将同步到数据列表。"
      />
      <DataLoadState isLoading={isLoading} error={error} onRetry={retry} />
      {!isLoading && !error && items.length === 0 && (
        <p className="data-empty">暂无可标注的数据。</p>
      )}
      {!isLoading && !error && items.length > 0 && (
        <div className="annotation-layout">
          <section aria-label="数据队列" className="annotation-queue">
            <div className="annotation-section-heading">
              <strong>数据队列</strong>
              <span>{total} 条</span>
            </div>
            {items.map((item) => (
              <button
                aria-pressed={selectedItem?.id === item.id}
                className={`annotation-queue-item${selectedItem?.id === item.id ? ' is-active' : ''}`}
                key={item.id}
                onClick={() => {
                  setSelectedId(item.id)
                  setChosenLabel(isDataLabel(item.label) ? item.label : '')
                  setSuccessMessage('')
                }}
                type="button"
              >
                <span className="annotation-queue-content">{item.content}</span>
                <span className={`data-status${item.label ? ' is-labeled' : ''}`}>
                  {item.label ?? '未标注'}
                </span>
              </button>
            ))}
            {pageCount > 1 && (
              <div className="annotation-pagination">
                <button
                  disabled={page <= 1}
                  onClick={() => {
                    setSelectedId(null)
                    setPage((currentPage) => currentPage - 1)
                  }}
                  type="button"
                >
                  上一页
                </button>
                <span>{page} / {pageCount}</span>
                <button
                  disabled={page >= pageCount}
                  onClick={() => {
                    setSelectedId(null)
                    setPage((currentPage) => currentPage + 1)
                  }}
                  type="button"
                >
                  下一页
                </button>
              </div>
            )}
          </section>
          {selectedItem && (
            <section aria-label="标注工作区" className="annotation-workspace">
              <div className="annotation-section-heading">
                <strong>数据内容</strong>
                <span>编号 #{selectedItem.id}</span>
              </div>
              <blockquote className="annotation-content">
                {selectedItem.content}
              </blockquote>
              <fieldset className="label-options">
                <legend>选择标注结果</legend>
                {LABEL_OPTIONS.map((label) => (
                  <label
                    className={`label-option${activeLabel === label ? ' is-selected' : ''}`}
                    key={label}
                  >
                    <input
                      checked={activeLabel === label}
                      name="data-label"
                      onChange={() => setChosenLabel(label)}
                      type="radio"
                      value={label}
                    />
                    <span>{label}</span>
                  </label>
                ))}
              </fieldset>
              {saveError && (
                <div className="annotation-save-error" role="alert">
                  <p className="form-error">{saveError}</p>
                  <button
                    className="welcome-action"
                    disabled={isSaving}
                    onClick={() => void handleSave()}
                    type="button"
                  >
                    {isSaving ? '重试中…' : '重试保存'}
                  </button>
                </div>
              )}
              {successMessage && (
                <p className="form-success" role="status">{successMessage}</p>
              )}
              <button
                className="welcome-action annotation-save"
                disabled={!activeLabel || isSaving}
                onClick={() => void handleSave()}
                type="button"
              >
                {isSaving ? '保存中…' : '保存标注'}
              </button>
            </section>
          )}
        </div>
      )}
    </>
  )
}
