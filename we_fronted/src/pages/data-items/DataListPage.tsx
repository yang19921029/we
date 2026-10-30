import { useEffect, useState } from 'react'
import {
  ApiError,
  getDatasets,
  type LabelStatusFilter,
  type DatasetRecord,
} from '../../api'
import { PAGE_SIZE, formatDate, useDataItems } from './dataItemsLogic'
import { DataPageHeading, DataLoadState } from './DataItemsShared'

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
  const [searchText, setSearchText] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [sortBy, setSortBy] = useState<'newest' | 'uncertain'>('newest')
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [datasetId, setDatasetId] = useState<number | undefined>()
  const [datasetError, setDatasetError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void getDatasets(controller.signal)
      .then(setDatasets)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && cause.status === 401) {
          onSessionExpired()
          return
        }
        setDatasetError(cause instanceof Error ? cause.message : '数据集加载失败。')
      })
    return () => controller.abort()
  }, [onSessionExpired])
  const { items, total, isLoading, error, retry } = useDataItems(
    onSessionExpired,
    page,
    PAGE_SIZE,
    labelStatus,
    datasetId,
    undefined,
    appliedSearch,
    sortBy,
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
        <label htmlFor="data-search">搜索</label>
        <input
          id="data-search"
          maxLength={200}
          onChange={(event) => setSearchText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              setAppliedSearch(searchText.trim())
              setPage(1)
              setPageInput('1')
            }
          }}
          placeholder="按编号或内容搜索"
          value={searchText}
        />
        <button
          className="platform-secondary-button"
          onClick={() => {
            setAppliedSearch(searchText.trim())
            setPage(1)
            setPageInput('1')
          }}
          type="button"
        >
          搜索
        </button>
        <label htmlFor="data-sort">排序</label>
        <select
          id="data-sort"
          onChange={(event) => setSortBy(event.target.value as typeof sortBy)}
          value={sortBy}
        >
          <option value="newest">最新数据</option>
          <option value="uncertain">优先低置信度</option>
        </select>
        <label htmlFor="dataset-filter">数据集</label>
        <select
          id="dataset-filter"
          onChange={(event) => {
            setDatasetId(event.target.value ? Number(event.target.value) : undefined)
            setPage(1)
            setPageInput('1')
          }}
          value={datasetId ?? ''}
        >
          <option value="">全部数据集</option>
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>{dataset.name}</option>
          ))}
        </select>
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
      {datasetError && <p className="platform-error" role="alert">{datasetError}</p>}
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
                  <th scope="col">标注时间</th>
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
