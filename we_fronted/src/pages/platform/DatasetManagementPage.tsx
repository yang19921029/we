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
import { PlatformModal } from './PlatformModal'
import { handlePageError } from '../pageErrors'
import { formatDate } from '../../dateFormat'

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
  const [dialog, setDialog] = useState<'create' | 'import' | null>(null)

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
      setDialog(null)
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
      setDialog(null)
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
      {error && <p className="platform-error" role="alert">{error}</p>}
      {status && <p className="platform-success" role="status">{status}</p>}
      <section className="platform-table-card">
        <div className="section-title-row">
          <div>
            <h2>数据集</h2>
            <p>{datasets.length} 个数据集</p>
          </div>
          <div className="platform-page-actions">
            <button className="platform-secondary-button" onClick={() => void loadDatasets()} type="button">
              刷新
            </button>
            <button
              className="platform-secondary-button"
              onClick={() => {
                setError('')
                setDialog('import')
              }}
              type="button"
            >
              导入数据
            </button>
            <button
              className="welcome-action"
              onClick={() => {
                setError('')
                setName('')
                setDescription('')
                setDialog('create')
              }}
              type="button"
            >
              创建数据集
            </button>
          </div>
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
                    <td>{formatDate(dataset.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {dialog === 'create' && (
        <PlatformModal onClose={() => setDialog(null)} title="创建数据集">
          <form className="platform-form-card" onSubmit={(event) => void handleCreate(event)}>
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
            {error && <p className="platform-error" role="alert">{error}</p>}
            <button className="welcome-action" disabled={isSaving || projects.length === 0} type="submit">
              创建数据集
            </button>
          </form>
        </PlatformModal>
      )}
      {dialog === 'import' && (
        <PlatformModal onClose={() => setDialog(null)} title="导入数据">
          <form className="platform-form-card" onSubmit={(event) => void handleImport(event)}>
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
              文件（CSV / JSON / JSONL，最大 1 GB）
              <input
                accept=".csv,.json,.jsonl,.ndjson"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                required
                type="file"
              />
            </label>
            <p className="platform-form-hint">
              JSON 支持对象数组或包含 items 数组的对象；记录条数不限，每条记录最大 50 MB。大文件上传需要服务端及代理预留足够临时磁盘空间。
            </p>
            {error && <p className="platform-error" role="alert">{error}</p>}
            <button className="welcome-action" disabled={!file || isSaving} type="submit">
              {isSaving ? '处理中…' : '开始导入'}
            </button>
          </form>
        </PlatformModal>
      )}
    </>
  )
}
