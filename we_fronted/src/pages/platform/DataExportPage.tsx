import { useEffect, useState } from 'react'
import {
  getDatasets,
  type DatasetRecord,
} from '../../api'
import { PageTitle } from './PlatformShared'

export function DataExportPage() {
  const [format, setFormat] = useState<'jsonl' | 'csv'>('jsonl')
  const [labelStatus, setLabelStatus] = useState('all')
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [datasetId, setDatasetId] = useState('')
  const [error, setError] = useState('')
  const query = new URLSearchParams({ format, label_status: labelStatus })
  if (datasetId) query.set('dataset_id', datasetId)
  useEffect(() => {
    void getDatasets()
      .then(setDatasets)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '数据集加载失败。'))
  }, [])
  return (
    <>
      <PageTitle
        eyebrow="DATA DELIVERY"
        title="数据导出"
        description="按标注状态导出当前索引数据。单次最多导出 10000 条，文件包含标注人和时间字段。"
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
    </>
  )
}
