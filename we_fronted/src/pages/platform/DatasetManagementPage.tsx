import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createDataset,
  getDatasets,
  getDatasetVersions,
  getProjects,
  importDatasetFile,
  previewDatasetFile,
  type DatasetImportPreview,
  type DatasetRecord,
  type DatasetVersion,
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
  const [importPreview, setImportPreview] = useState<DatasetImportPreview | null>(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [dialog, setDialog] = useState<'create' | 'import' | null>(null)
  const [versionDataset, setVersionDataset] = useState<DatasetRecord | null>(null)
  const [datasetVersions, setDatasetVersions] = useState<DatasetVersion[]>([])
  const [isLoadingVersions, setIsLoadingVersions] = useState(false)

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
    if (!datasetId || !file || !importPreview) return
    setIsSaving(true)
    setError('')
    setStatus('')
    try {
      const result = await importDatasetFile(Number(datasetId), file)
      setStatus(
        `成功导入 ${result.imported_count} 条记录。${
          result.dataset_version ? ` 数据集版本已更新至 v${result.dataset_version}。` : ''
        }`,
      )
      setFile(null)
      setImportPreview(null)
      setDialog(null)
      await loadDatasets()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '数据导入失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  async function handlePreflight() {
    if (!datasetId || !file) return
    setIsSaving(true)
    setError('')
    setStatus('')
    setImportPreview(null)
    try {
      setImportPreview(await previewDatasetFile(Number(datasetId), file))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '文件预检失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  async function showVersionHistory(dataset: DatasetRecord) {
    setVersionDataset(dataset)
    setIsLoadingVersions(true)
    setError('')
    try {
      setDatasetVersions(await getDatasetVersions(dataset.id))
    } catch (cause) {
      setVersionDataset(null)
      setError(handlePageError(cause, onSessionExpired, '数据集版本历史加载失败。'))
    } finally {
      setIsLoadingVersions(false)
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
                  <th scope="col">版本</th>
                  <th scope="col">创建人</th>
                  <th scope="col">创建时间</th>
                  <th scope="col">操作</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((dataset) => (
                  <tr key={dataset.id}>
                    <td>{dataset.name}</td>
                    <td>{dataset.project_name}</td>
                    <td>{dataset.description || '—'}</td>
                    <td>{dataset.record_count}</td>
                    <td>{dataset.latest_version ? `v${dataset.latest_version}` : '尚无导入版本'}</td>
                    <td>{dataset.created_by}</td>
                    <td>{formatDate(dataset.created_at)}</td>
                    <td>
                      <button className="text-link" onClick={() => void showVersionHistory(dataset)} type="button">
                        版本历史
                      </button>
                    </td>
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
                onChange={(event) => {
                  setDatasetId(event.target.value)
                  setImportPreview(null)
                }}
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
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null)
                  setImportPreview(null)
                }}
                required
                type="file"
              />
            </label>
            <p className="platform-form-hint">
              JSON 支持对象数组、包含 items 数组的对象或单个对象；每条记录必须为对象且最大 50 MB。先执行文件预检，确认记录数量、字段和样例后再导入。大文件预检需要上传完整文件。
            </p>
            {importPreview && (
              <section className="platform-table-card" aria-label="文件预检结果">
                <h3>文件预检通过</h3>
                <p>检测到 {importPreview.record_count.toLocaleString()} 条记录。</p>
                <p>字段：{importPreview.fields.join('、') || '无'}</p>
                <p>以下为前 {importPreview.preview.length} 条样例：</p>
                <pre className="platform-import-preview">
                  {JSON.stringify(importPreview.preview, null, 2)}
                </pre>
              </section>
            )}
            {versionDataset && (
              <PlatformModal
                onClose={() => setVersionDataset(null)}
                title={`数据集「${versionDataset.name}」版本历史`}
              >
                {isLoadingVersions ? (
                  <p className="api-message" role="status">正在加载版本历史…</p>
                ) : datasetVersions.length === 0 ? (
                  <p className="data-empty">该数据集还没有成功写入的导入版本。</p>
                ) : (
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">版本</th>
                          <th scope="col">写入数</th>
                          <th scope="col">状态</th>
                          <th scope="col">文件</th>
                          <th scope="col">操作人 / 时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {datasetVersions.map((version) => (
                          <tr key={version.id}>
                            <td>v{version.version}</td>
                            <td>{version.imported_count}</td>
                            <td>{version.status}</td>
                            <td>{version.source_name}</td>
                            <td>{version.created_by} / {formatDate(version.created_at)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </PlatformModal>
            )}
            {error && <p className="platform-error" role="alert">{error}</p>}
            {!importPreview ? (
              <button
                className="welcome-action"
                disabled={!file || isSaving || !datasetId}
                onClick={(event) => {
                  event.preventDefault()
                  void handlePreflight()
                }}
                type="button"
              >
                {isSaving ? '正在预检…' : '预检文件'}
              </button>
            ) : (
              <button className="welcome-action" disabled={isSaving} type="submit">
                {isSaving ? '正在导入…' : '确认并导入'}
              </button>
            )}
          </form>
        </PlatformModal>
      )}
    </>
  )
}
