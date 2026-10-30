import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createDataset,
  getDatasets,
  getProjects,
  importDatasetFile,
  type DatasetRecord,
  type ProjectRecord,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { handlePageError } from '../pageErrors'

export function DatasetManagementPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [datasets, setDatasets] = useState<DatasetRecord[]>([])
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState('')
  const [datasetId, setDatasetId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)

  const loadDatasets = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const [nextDatasets, nextProjects] = await Promise.all([
        getDatasets(),
        getProjects(),
      ])
      setDatasets(nextDatasets)
      setProjects(nextProjects)
      setProjectId((current) => current || String(nextProjects[0]?.id ?? ''))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '数据集加载失败。'))
    } finally {
      setIsLoading(false)
    }
  }, [onSessionExpired])

  useEffect(() => {
    void loadDatasets()
  }, [loadDatasets])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSaving(true)
    setError('')
    setStatus('')
    try {
      const dataset = await createDataset(
        name.trim(),
        description.trim(),
        Number(projectId),
      )
      setDatasets((current) => [...current, dataset])
      setDatasetId(String(dataset.id))
      setName('')
      setDescription('')
      setStatus(`数据集「${dataset.name}」已创建。`)
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '数据集创建失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!datasetId || !file) return
    setIsSaving(true)
    setError('')
    setStatus('')
    try {
      const result = await importDatasetFile(Number(datasetId), file)
      setStatus(`成功导入 ${result.imported_count} 条记录。`)
      setFile(null)
      event.currentTarget.reset()
      await loadDatasets()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '数据导入失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="DATA MANAGEMENT"
        title="数据集管理"
        description="创建数据集并导入 CSV、JSON 或 JSONL 文件；导入记录将进入标注队列。"
      />
      <div className="platform-form-grid">
        <form className="platform-form-card" onSubmit={(event) => void handleCreate(event)}>
          <h2>创建数据集</h2>
          <label>
            数据集名称
            <input
              maxLength={191}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </label>
          <label>
            所属项目
            <select
              onChange={(event) => setProjectId(event.target.value)}
              required
              value={projectId}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.organization_name} / {project.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            说明
            <textarea
              maxLength={2000}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              value={description}
            />
          </label>
          <button className="welcome-action" disabled={isSaving || projects.length === 0} type="submit">
            创建数据集
          </button>
        </form>
        <form className="platform-form-card" onSubmit={(event) => void handleImport(event)}>
          <h2>导入数据</h2>
          <label>
            目标数据集
            <select
              onChange={(event) => setDatasetId(event.target.value)}
              required
              value={datasetId}
            >
              <option value="">请选择数据集</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            文件（CSV / JSON / JSONL，最大 10 MB）
            <input
              accept=".csv,.json,.jsonl,.ndjson"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              required
              type="file"
            />
          </label>
          <p className="platform-form-hint">
            JSON 支持对象数组或包含 items 数组的对象；每条记录应为 JSON 对象。
          </p>
          <button className="welcome-action" disabled={!file || isSaving} type="submit">
            {isSaving ? '处理中…' : '开始导入'}
          </button>
        </form>
      </div>
      {error && <p className="platform-error" role="alert">{error}</p>}
      {status && <p className="platform-success" role="status">{status}</p>}
      <section className="platform-table-card">
        <div className="section-title-row">
          <div>
            <h2>数据集</h2>
            <p>{datasets.length} 个数据集</p>
          </div>
          <button className="platform-secondary-button" onClick={() => void loadDatasets()} type="button">
            刷新
          </button>
        </div>
        {isLoading ? (
          <p className="api-message" role="status">正在加载数据集…</p>
        ) : datasets.length === 0 ? (
          <p className="data-empty">暂无数据集。</p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">名称</th>
                  <th scope="col">项目</th>
                  <th scope="col">说明</th>
                  <th scope="col">记录数</th>
                  <th scope="col">创建人</th>
                  <th scope="col">创建时间</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((dataset) => (
                  <tr key={dataset.id}>
                    <td>{dataset.name}</td>
                    <td>{dataset.project_name}</td>
                    <td>{dataset.description || '—'}</td>
                    <td>{dataset.record_count}</td>
                    <td>{dataset.created_by}</td>
                    <td>{dataset.created_at ? String(dataset.created_at).slice(0, 10) : '—'}</td>
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
