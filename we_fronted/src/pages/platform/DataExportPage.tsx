import { useCallback, useEffect, useState } from 'react'
import {
  getDatasets,
  getExportHistory,
  type DatasetRecord,
  type ExportHistoryRecord,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { formatDate } from '../../dateFormat'
import { handlePageError } from '../pageErrors'

export function DataExportPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [format, setFormat] = useState<'jsonl' | 'csv'>('jsonl')
  const [labelStatus, setLabelStatus] = useState('all')
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [datasetId, setDatasetId] = useState('')
  const [error, setError] = useState('')
  const [history, setHistory] = useState<ExportHistoryRecord[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const query = new URLSearchParams({ format, label_status: labelStatus })
  if (datasetId) query.set('dataset_id', datasetId)
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    setError('')
    try {
      setHistory((await getExportHistory()).items)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '导出历史加载失败。'))
    } finally {
      setHistoryLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void getDatasets()
      .then(setDatasets)
      .catch((cause: unknown) => setError(
        handlePageError(cause, onSessionExpired, '数据集加载失败。'),
      ))
    void loadHistory()
  }, [loadHistory, onSessionExpired])
  return (
    <>
      <PageTitle
        eyebrow="DATA DELIVERY"
        title="数据导出"
        description="按数据集和标注状态导出匹配数据。大数据集将分页读取并流式生成文件，文件包含标注人和时间字段。"
      />
      <section className="platform-form-card platform-export-card">
        <label>
          数据集
          <select onChange={(event) => setDatasetId(event.target.value)} value={datasetId}>
            <option value="">全部数据集</option>
            {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
          </select>
        </label>
        <label>
          标注状态
          <select onChange={(event) => setLabelStatus(event.target.value)} value={labelStatus}>
            <option value="all">全部数据</option>
            <option value="labeled">已标注</option>
            <option value="unlabeled">未标注</option>
            <option value="正向">正向</option>
            <option value="中性">中性</option>
            <option value="负向">负向</option>
          </select>
        </label>
        <label>
          文件格式
          <select onChange={(event) => setFormat(event.target.value as typeof format)} value={format}>
            <option value="jsonl">JSONL</option>
            <option value="csv">CSV</option>
          </select>
        </label>
        <a className="welcome-action platform-download-link" href={`/api/data-items/export?${query}`}>
          下载标注数据
        </a>
        {error && <p className="platform-error" role="alert">{error}</p>}
      </section>
      <section className="platform-table-card">
        <div className="section-title-row">
          <div>
            <h2>导出历史</h2>
            <p>仅显示当前账号发起的最近 20 次导出。</p>
          </div>
          <button
            className="platform-secondary-button"
            disabled={historyLoading}
            onClick={() => void loadHistory()}
            type="button"
          >
            刷新
          </button>
        </div>
        {historyLoading ? (
          <p className="api-message" role="status">正在加载导出历史…</p>
        ) : history.length === 0 ? (
          <p className="data-empty">暂无导出记录。</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">发起时间</th>
                  <th scope="col">数据集</th>
                  <th scope="col">筛选条件</th>
                  <th scope="col">格式</th>
                  <th scope="col">状态</th>
                  <th scope="col">记录数</th>
                  <th scope="col">完成时间</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={entry.id}>
                    <td>{formatDate(entry.created_at)}</td>
                    <td>
                      {entry.dataset_id
                        ? datasets.find((dataset) => dataset.id === entry.dataset_id)?.name ?? `#${entry.dataset_id}`
                        : '全部可访问数据'}
                    </td>
                    <td>{entry.label_status}</td>
                    <td>{entry.export_format.toUpperCase()}</td>
                    <td>{entry.status}</td>
                    <td>{entry.item_count}</td>
                    <td>{formatDate(entry.completed_at)}</td>
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
