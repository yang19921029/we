import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  createLabelSchema,
  getLabelSchemas,
  getLabelSchemaVersions,
  updateLabelSchema,
  type LabelOption,
  type LabelSchema,
} from '../../api'
import { PageTitle } from './PlatformShared'
import { PlatformModal } from './PlatformModal'
import { handlePageError } from '../pageErrors'
import { formatDate } from '../../dateFormat'

export function LabelSchemaPage({
  onSessionExpired,
}: {
  onSessionExpired: () => void
}) {
  const [schemas, setSchemas] = useState<LabelSchema[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [labelsText, setLabelsText] = useState(
    JSON.stringify(
      [
        { code: 'positive', name: '正向', color: '#2d9b6f' },
        { code: 'neutral', name: '中性', color: '#d99b37' },
        { code: 'negative', name: '负向', color: '#d65b57' },
      ],
      null,
      2,
    ),
  )
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [versions, setVersions] = useState<Array<{ version: number; changed_by: string; changed_at: string }>>([])
  const [isSaving, setIsSaving] = useState(false)
  const [isCreateOpen, setIsCreateOpen] = useState(false)

  const loadSchemas = useCallback(async () => {
    try {
      const result = await getLabelSchemas()
      setSchemas(result)
      setSelectedId((current) => current || String(result[0]?.id ?? ''))
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '标签体系加载失败。'))
    }
  }, [onSessionExpired])

  useEffect(() => {
    void loadSchemas()
  }, [loadSchemas])

  const selectedSchema = schemas.find((schema) => String(schema.id) === selectedId)
  useEffect(() => {
    if (!selectedSchema) return
    setName(selectedSchema.name)
    setDescription(selectedSchema.description)
    setLabelsText(JSON.stringify(selectedSchema.labels, null, 2))
    void getLabelSchemaVersions(selectedSchema.id)
      .then(setVersions)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : '标签版本加载失败。'))
  }, [selectedSchema])

  async function handleSave(
    event: FormEvent<HTMLFormElement>,
    create = false,
  ) {
    event.preventDefault()
    setError('')
    setStatus('')
    setIsSaving(true)
    let labels: LabelOption[]
    try {
      labels = JSON.parse(labelsText) as LabelOption[]
    } catch {
      setError('标签配置必须是有效的 JSON 数组。')
      setIsSaving(false)
      return
    }
    try {
      if (!create && selectedSchema) {
        await updateLabelSchema(selectedSchema.id, description, labels)
        setStatus('标签体系已保存，新配置已生成版本记录。')
      } else {
        const schema = await createLabelSchema(name, description, labels)
        setSelectedId(String(schema.id))
        setStatus('标签体系已创建。')
        setIsCreateOpen(false)
      }
      await loadSchemas()
    } catch (cause) {
      setError(handlePageError(cause, onSessionExpired, '标签体系保存失败。'))
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <>
      <PageTitle
        eyebrow="LABEL SCHEMA"
        title="标签体系管理"
        description="配置唯一编码、标签名称和颜色；更新会保留版本历史，供标注任务复用。"
      />
      <div className="platform-schema-layout">
        <section className="platform-table-card">
          <div className="section-title-row">
            <div><h2>标签体系</h2><p>{schemas.length} 个体系</p></div>
            <button
              className="welcome-action"
              onClick={() => {
                setName('')
                setDescription('')
                setLabelsText(
                  JSON.stringify(
                    [
                      { code: 'positive', name: '正向', color: '#2d9b6f' },
                      { code: 'neutral', name: '中性', color: '#d99b37' },
                      { code: 'negative', name: '负向', color: '#d65b57' },
                    ],
                    null,
                    2,
                  ),
                )
                setError('')
                setIsCreateOpen(true)
              }}
              type="button"
            >
              新建标签体系
            </button>
          </div>
          {schemas.map((schema) => (
            <button
              className={`platform-schema-item${selectedId === String(schema.id) ? ' is-active' : ''}`}
              key={schema.id}
              onClick={() => setSelectedId(String(schema.id))}
              type="button"
            >
              <span>{schema.name}</span><small>v{schema.version} · {schema.labels.length} 个标签</small>
            </button>
          ))}
        </section>
        {selectedSchema && <form className="platform-form-card" onSubmit={(event) => void handleSave(event)}>
          <h2>编辑：{selectedSchema.name}</h2>
          <label>
            说明
            <textarea maxLength={2000} onChange={(event) => setDescription(event.target.value)} rows={2} value={description} />
          </label>
          <label>
            标签配置（至少 2 项；code 唯一，color 为十六进制颜色）
            <textarea
              className="platform-code-input"
              onChange={(event) => setLabelsText(event.target.value)}
              required
              rows={12}
              value={labelsText}
            />
          </label>
          <button className="welcome-action" disabled={isSaving} type="submit">
            {isSaving ? '保存中…' : '保存并创建新版本'}
          </button>
          {error && <p className="platform-error" role="alert">{error}</p>}
          {status && <p className="platform-success" role="status">{status}</p>}
          {versions.length > 0 && (
            <div className="platform-version-list">
              <strong>版本历史</strong>
              {versions.map((version) => (
                <span key={version.version}>
                  v{version.version} · {version.changed_by} · {formatDate(version.changed_at)}
                </span>
              ))}
            </div>
          )}
        </form>}
      </div>
      {isCreateOpen && (
        <PlatformModal onClose={() => setIsCreateOpen(false)} title="创建标签体系">
          <form className="platform-form-card" onSubmit={(event) => void handleSave(event, true)}>
            <label>
              体系名称
              <input maxLength={191} onChange={(event) => setName(event.target.value)} required value={name} />
            </label>
            <label>
              说明
              <textarea maxLength={2000} onChange={(event) => setDescription(event.target.value)} rows={2} value={description} />
            </label>
            <label>
              标签配置（至少 2 项；code 唯一，color 为十六进制颜色）
              <textarea
                className="platform-code-input"
                onChange={(event) => setLabelsText(event.target.value)}
                required
                rows={12}
                value={labelsText}
              />
            </label>
            {error && <p className="platform-error" role="alert">{error}</p>}
            <button className="welcome-action" disabled={isSaving} type="submit">
              {isSaving ? '创建中…' : '创建体系'}
            </button>
          </form>
        </PlatformModal>
      )}
    </>
  )
}
