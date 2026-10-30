import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  getAnnotationTasks,
  getLabelSchemas,
  reportDataItemIssue,
  preannotateDataItem,
  skipTaskItem,
  updateAnnotationTask,
  type AnnotationTask,
  type DataItem,
  type DataItemIssueType,
  type DataLabel,
  type LabelSchema,
  type AIAnnotationSuggestion,
  type MultimodalAnnotation,
} from '../../api'
import { LABEL_OPTIONS, ANNOTATION_PAGE_SIZE, isDataLabel, getLabelHistory, formatDate, useDataItems } from './dataItemsLogic'
import { DataPageHeading, DataLoadState } from './DataItemsShared'
import { getMediaPreviews } from './mediaPreview'
import { MultimodalAnnotationEditor } from './MultimodalAnnotationEditor'

export function DataLabelPage({
  onSessionExpired,
  initialTaskId,
}: {
  onSessionExpired: () => void
  initialTaskId?: number
}) {
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tasks, setTasks] = useState<AnnotationTask[]>([])
  const [schemas, setSchemas] = useState<LabelSchema[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState(
    initialTaskId ? String(initialTaskId) : '',
  )
  const [taskError, setTaskError] = useState('')
  const [aiSuggestion, setAiSuggestion] = useState<AIAnnotationSuggestion | null>(null)
  const [isSuggesting, setIsSuggesting] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([
      getAnnotationTasks(controller.signal),
      getLabelSchemas(controller.signal),
    ])
      .then(([taskList, schemaList]) => {
        setTasks(taskList)
        setSchemas(schemaList)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        if (cause instanceof ApiError && cause.status === 401) {
          onSessionExpired()
          return
        }
        setTaskError(cause instanceof Error ? cause.message : '任务配置加载失败。')
      })
    return () => controller.abort()
  }, [onSessionExpired])
  const selectedTask = tasks.find((task) => String(task.id) === selectedTaskId)
  const activeSchema = schemas.find(
    (schema) => schema.id === selectedTask?.label_schema_id,
  )
  const labelChoices = activeSchema
    ? activeSchema.labels.map((label) => label.name)
    : LABEL_OPTIONS
  const { items, total, isLoading, error, retry, saveLabel } = useDataItems(
    onSessionExpired,
    page,
    ANNOTATION_PAGE_SIZE,
    'all',
    selectedTask?.dataset_id,
    selectedTask?.id,
  )
  const [chosenLabel, setChosenLabel] = useState<DataLabel | null>(null)
  const [labelHistory, setLabelHistory] = useState<Array<DataLabel | null>>([null])
  const [historyIndex, setHistoryIndex] = useState(0)
  const [isDirty, setIsDirty] = useState(false)
  const [annotation, setAnnotation] = useState<MultimodalAnnotation | null>(null)
  const [annotationDirty, setAnnotationDirty] = useState(false)
  const [autoSaveBlocked, setAutoSaveBlocked] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveStatus, setSaveStatus] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [issueType, setIssueType] = useState<DataItemIssueType>('数据异常')
  const [issueDescription, setIssueDescription] = useState('')
  const [issueError, setIssueError] = useState('')
  const [issueStatus, setIssueStatus] = useState('')
  const [isReportingIssue, setIsReportingIssue] = useState(false)
  const [locallySkippedIds, setLocallySkippedIds] = useState<Set<string>>(
    () => new Set(),
  )
  const visibleItems = items.filter((item) => !locallySkippedIds.has(item.id))
  const saveVersion = useRef(0)
  const selectedIdRef = useRef<string | null>(selectedId)
  const selectedItem =
    visibleItems.find((item) => item.id === selectedId) ??
    visibleItems.find((item) => item.label === null) ??
    visibleItems[0]
  const activeLabel = chosenLabel
  const selectedMedia = selectedItem ? getMediaPreviews(selectedItem.fields) : []
  const pageCount = Math.max(1, Math.ceil(total / ANNOTATION_PAGE_SIZE))

  useEffect(() => {
    if (!selectedItem) return
    selectedIdRef.current = selectedItem.id
    const initialLabel = isDataLabel(selectedItem.label)
      ? selectedItem.label
      : null
    setChosenLabel(initialLabel)
    setLabelHistory([initialLabel])
    setHistoryIndex(0)
    setIsDirty(false)
    setAnnotation(selectedItem.annotation)
    setAnnotationDirty(false)
    setAutoSaveBlocked(false)
    setSaveError('')
    setSaveStatus('')
    setIssueError('')
    setIssueStatus('')
    setAiSuggestion(null)
  }, [selectedItem])

  useEffect(() => {
    if (!selectedItem || (!isDirty && !annotationDirty) || autoSaveBlocked) return
    const itemId = selectedItem.id
    const label = isDirty ? activeLabel : selectedItem.label
    const annotationToSave = annotationDirty ? annotation ?? { items: [] } : undefined
    const version = saveVersion.current
    const timeout = window.setTimeout(() => {
      setIsSaving(true)
      setSaveError('')
      void saveLabel(itemId, label, annotationToSave)
        .then(() => {
          if (
            saveVersion.current === version &&
            selectedIdRef.current === itemId
          ) {
            setIsDirty(false)
            setAnnotationDirty(false)
            setSaveStatus('已自动保存')
          }
        })
        .catch((cause: unknown) => {
          if (saveVersion.current !== version) return
          setAutoSaveBlocked(true)
          setSaveError(cause instanceof Error ? cause.message : '自动保存失败。')
        })
        .finally(() => setIsSaving(false))
    }, 500)
    return () => window.clearTimeout(timeout)
  }, [activeLabel, annotation, annotationDirty, autoSaveBlocked, isDirty, saveLabel, selectedItem])

  function flushPendingSave() {
    if (!selectedItem || (!isDirty && !annotationDirty)) return
    const labelWasDirty = isDirty
    const annotationWasDirty = annotationDirty
    const itemId = selectedItem.id
    const label = isDirty ? activeLabel : selectedItem.label
    const annotationToSave = annotationDirty ? annotation ?? { items: [] } : undefined
    saveVersion.current += 1
    setIsDirty(false)
    setAnnotationDirty(false)
    setIsSaving(true)
    void saveLabel(itemId, label, annotationToSave)
      .then(() => setSaveStatus('已自动保存'))
      .catch((cause: unknown) => {
        setIsDirty(labelWasDirty)
        setAnnotationDirty(annotationWasDirty)
        setAutoSaveBlocked(true)
        setSaveError(cause instanceof Error ? cause.message : '自动保存失败。')
      })
      .finally(() => setIsSaving(false))
  }

  async function persistPendingChanges() {
    if (!selectedItem || (!isDirty && !annotationDirty)) return
    const labelWasDirty = isDirty
    const annotationWasDirty = annotationDirty
    const label = labelWasDirty ? activeLabel : selectedItem.label
    const annotationToSave = annotationWasDirty
      ? annotation ?? { items: [] }
      : undefined
    saveVersion.current += 1
    setIsDirty(false)
    setAnnotationDirty(false)
    setIsSaving(true)
    try {
      await saveLabel(selectedItem.id, label, annotationToSave)
      setSaveStatus('已自动保存')
    } catch (cause) {
      setIsDirty(labelWasDirty)
      setAnnotationDirty(annotationWasDirty)
      setAutoSaveBlocked(true)
      throw cause
    } finally {
      setIsSaving(false)
    }
  }

  function selectItem(item: DataItem, flush = true) {
    if (flush) flushPendingSave()
    saveVersion.current += 1
    selectedIdRef.current = item.id
    setSelectedId(item.id)
    const nextLabel = isDataLabel(item.label) ? item.label : null
    setChosenLabel(nextLabel)
    setLabelHistory([nextLabel])
    setHistoryIndex(0)
    setIsDirty(false)
    setAnnotation(item.annotation)
    setAnnotationDirty(false)
    setAutoSaveBlocked(false)
    setSaveError('')
    setSaveStatus('')
    setIssueError('')
    setIssueStatus('')
  }

  function updateAnnotation(nextAnnotation: MultimodalAnnotation) {
    saveVersion.current += 1
    setAnnotation(nextAnnotation)
    setAnnotationDirty(true)
    setAutoSaveBlocked(false)
    setSaveError('')
    setSaveStatus('多模态标注已修改，等待自动保存…')
  }

  async function toggleTaskPause() {
    if (!selectedTask) return
    const nextStatus = selectedTask.status === '已暂停' ? '标注中' : '已暂停'
    try {
      await persistPendingChanges()
      await updateAnnotationTask(selectedTask.id, { status: nextStatus })
      setTasks((current) =>
        current.map((task) =>
          task.id === selectedTask.id ? { ...task, status: nextStatus } : task,
        ),
      )
    } catch (cause) {
      setTaskError(cause instanceof Error ? cause.message : '任务状态更新失败。')
    }
  }

  async function requestAISuggestion() {
    if (!selectedItem || !selectedTask) return
    setTaskError('')
    setAiSuggestion(null)
    setIsSuggesting(true)
    try {
      setAiSuggestion(await preannotateDataItem(selectedItem.id, selectedTask.id))
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired()
      }
      setTaskError(cause instanceof Error ? cause.message : 'AI 预标注请求失败。')
    } finally {
      setIsSuggesting(false)
    }
  }

  async function skipCurrentItem() {
    if (!selectedItem || !selectedTask) return
    try {
      await persistPendingChanges()
      await skipTaskItem(selectedTask.id, selectedItem.id)
      const currentIndex = visibleItems.findIndex((item) => item.id === selectedItem.id)
      const nextItem = visibleItems[currentIndex + 1]
      setLocallySkippedIds((current) => new Set(current).add(selectedItem.id))
      if (nextItem) selectItem(nextItem, false)
      else setSelectedId(null)
    } catch (cause) {
      setTaskError(cause instanceof Error ? cause.message : '跳过数据失败。')
    }
  }

  function chooseLabel(label: DataLabel) {
    const nextHistory = labelHistory.slice(0, historyIndex + 1)
    if (nextHistory[nextHistory.length - 1] !== label) {
      nextHistory.push(label)
      setLabelHistory(nextHistory)
      setHistoryIndex(nextHistory.length - 1)
    }
    saveVersion.current += 1
    setChosenLabel(label)
    setIsDirty(true)
    setAutoSaveBlocked(false)
    setSaveError('')
    setSaveStatus('正在保存…')
  }

  function undoLabel() {
    if (historyIndex <= 0) return
    const nextIndex = historyIndex - 1
    setHistoryIndex(nextIndex)
    saveVersion.current += 1
    setChosenLabel(labelHistory[nextIndex])
    setIsDirty(true)
    setAutoSaveBlocked(false)
    setSaveStatus('已撤销，等待保存…')
    setSaveError('')
  }

  function redoLabel() {
    if (historyIndex >= labelHistory.length - 1) return
    const nextIndex = historyIndex + 1
    setHistoryIndex(nextIndex)
    saveVersion.current += 1
    setChosenLabel(labelHistory[nextIndex])
    setIsDirty(true)
    setAutoSaveBlocked(false)
    setSaveStatus('已重做，等待保存…')
    setSaveError('')
  }

  function navigateItem(offset: -1 | 1) {
    if (!selectedItem) return
    const currentIndex = visibleItems.findIndex((item) => item.id === selectedItem.id)
    const nextItem = visibleItems[currentIndex + offset]
    if (nextItem) {
      selectItem(nextItem)
      return
    }
    const nextPage = page + offset
    if (nextPage < 1 || nextPage > pageCount) return
    flushPendingSave()
    selectedIdRef.current = null
    setSelectedId(null)
    setPage(nextPage)
  }

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName))
      ) {
        return
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redoLabel()
        else undoLabel()
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        navigateItem(-1)
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        navigateItem(1)
      } else if (event.key === '1') {
        chooseLabel(LABEL_OPTIONS[0])
      } else if (event.key === '2') {
        chooseLabel(LABEL_OPTIONS[1])
      } else if (event.key === '3') {
        chooseLabel(LABEL_OPTIONS[2])
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  })

  async function handleSave() {
    if (!selectedItem || (!isDirty && !annotationDirty)) return
    const labelWasDirty = isDirty
    const annotationWasDirty = annotationDirty
    const label = isDirty ? activeLabel : selectedItem.label
    saveVersion.current += 1
    setSaveError('')
    setSaveStatus('正在保存…')
    setAutoSaveBlocked(false)
    setIsDirty(false)
    setIsSaving(true)
    try {
      await saveLabel(
        selectedItem.id,
        label,
        annotationDirty ? annotation ?? { items: [] } : undefined,
      )
      setAnnotationDirty(false)
      setAutoSaveBlocked(false)
      setSaveStatus(`数据 #${selectedItem.id} 已保存`)
    } catch (cause) {
      setIsDirty(labelWasDirty)
      setAnnotationDirty(annotationWasDirty)
      setAutoSaveBlocked(true)
      setSaveError(cause instanceof Error ? cause.message : '保存标注失败。')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleIssueReport() {
    if (!selectedItem || !issueDescription.trim()) return
    setIssueError('')
    setIssueStatus('')
    setIsReportingIssue(true)
    try {
      await reportDataItemIssue(
        selectedItem.id,
        issueType,
        issueDescription.trim(),
      )
      setIssueDescription('')
      setIssueStatus('异常反馈已提交。')
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired()
      }
      setIssueError(cause instanceof Error ? cause.message : '异常反馈提交失败。')
    } finally {
      setIsReportingIssue(false)
    }
  }

  return (
    <>
      <DataPageHeading
        eyebrow="DATA ANNOTATION"
        title="数据打标"
        description="从数据集任务中领取数据并完成标注。标注会自动保存，也可以使用快捷键和撤销/重做提高效率。"
      />
      {taskError && <p className="platform-error" role="alert">{taskError}</p>}
      <div className="annotation-task-selector">
        <label htmlFor="annotation-task">当前标注任务</label>
        <select
          id="annotation-task"
          onChange={(event) => {
            flushPendingSave()
            setSelectedTaskId(event.target.value)
            setPage(1)
            setSelectedId(null)
            selectedIdRef.current = null
            setIsDirty(false)
            setAnnotation(null)
            setAnnotationDirty(false)
            setSaveError('')
          }}
          value={selectedTaskId}
        >
          <option value="">全部数据（兼容模式）</option>
          {tasks.map((task) => (
            <option key={task.id} value={task.id}>
              {task.name} · {task.status} · {task.assignee}
            </option>
          ))}
        </select>
        {selectedTask?.instructions && (
          <span>{selectedTask.instructions}</span>
        )}
        {selectedTask && (
          <>
            <button
              className="platform-secondary-button"
              onClick={() => void toggleTaskPause()}
              type="button"
            >
              {selectedTask.status === '已暂停' ? '继续任务' : '暂停任务'}
            </button>
            <button
              className="platform-secondary-button"
              disabled={isSuggesting || selectedTask.status === '已暂停'}
              onClick={() => void requestAISuggestion()}
              type="button"
            >
              {isSuggesting ? 'AI 分析中…' : 'AI 预标注'}
            </button>
          </>
        )}
      </div>
      {aiSuggestion && (
        <div className="platform-ai-suggestion" role="status">
          <div>
            <strong>AI 建议：{aiSuggestion.label}</strong>
            <span>置信度 {(aiSuggestion.confidence * 100).toFixed(1)}% · {aiSuggestion.model}</span>
            <p>{aiSuggestion.reason}</p>
          </div>
          <button
            className="welcome-action"
            disabled={selectedTask?.status === '已暂停'}
            onClick={() => {
              chooseLabel(aiSuggestion.label)
              setAiSuggestion(null)
            }}
            type="button"
          >
            采用建议
          </button>
        </div>
      )}
      <DataLoadState isLoading={isLoading} error={error} onRetry={retry} />
      {!isLoading && !error && visibleItems.length === 0 && (
        <p className="data-empty">暂无可标注的数据。</p>
      )}
      {!isLoading && !error && items.length > 0 && (
        <div className="annotation-layout">
          <section aria-label="数据队列" className="annotation-queue">
            <div className="annotation-section-heading">
              <strong>数据队列</strong>
              <span>{total} 条</span>
            </div>
            {visibleItems.map((item) => (
              <button
                aria-pressed={selectedItem?.id === item.id}
                className={`annotation-queue-item${selectedItem?.id === item.id ? ' is-active' : ''}`}
                key={item.id}
                onClick={() => selectItem(item)}
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
                    flushPendingSave()
                    selectedIdRef.current = null
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
                    flushPendingSave()
                    selectedIdRef.current = null
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
              <div className="annotation-controls">
                <button
                  disabled={historyIndex <= 0}
                  onClick={undoLabel}
                  type="button"
                >
                  撤销 <kbd>Ctrl/⌘ Z</kbd>
                </button>
                <button
                  disabled={historyIndex >= labelHistory.length - 1}
                  onClick={redoLabel}
                  type="button"
                >
                  重做 <kbd>Ctrl/⌘ Shift Z</kbd>
                </button>
                <span>方向键切换数据 · 1/2/3 快速选择标签</span>
              </div>
              <blockquote className="annotation-content">
                {selectedItem.content}
              </blockquote>
              {selectedMedia.length > 0 && (
                <MultimodalAnnotationEditor
                  annotation={annotation}
                  label={activeLabel}
                  media={selectedMedia}
                  onChange={updateAnnotation}
                />
              )}
              <details className="annotation-guidelines">
                <summary>查看标注规范</summary>
                {activeSchema ? (
                  <>
                    <p>{activeSchema.description || selectedTask?.instructions || '按照所选标签体系完成标注。'}</p>
                    <ul>
                      {activeSchema.labels.map((label) => (
                        <li key={label.code}>
                          <span className="schema-color-dot" style={{ backgroundColor: label.color }} />
                          {label.name}（{label.code}）
                        </li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <ul>
                    <li>正向：表达满意、赞扬或积极态度。</li>
                    <li>中性：客观陈述，或褒贬倾向不明显。</li>
                    <li>负向：表达不满、投诉或消极态度。</li>
                    <li>根据文本整体语义判断，不确定时请提交异常反馈。</li>
                  </ul>
                )}
              </details>
              <fieldset className="label-options">
                <legend>选择标注结果</legend>
                {labelChoices.map((label, index) => (
                  <label
                    className={`label-option${activeLabel === label ? ' is-selected' : ''}`}
                    key={label}
                  >
                    <input
                      checked={activeLabel === label}
                      name="data-label"
                      onChange={() => chooseLabel(label)}
                      type="radio"
                    />
                    <span>{label} <kbd>{index + 1}</kbd></span>
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
              {saveStatus && !saveError && (
                <p className="annotation-save-status" role="status">{saveStatus}</p>
              )}
              <div className="annotation-action-row">
                <button
                  className="welcome-action annotation-save"
                  disabled={
                    (!isDirty && !annotationDirty) ||
                    (isDirty && activeLabel === null) ||
                    isSaving
                  }
                  onClick={() => void handleSave()}
                  type="button"
                >
                  {isSaving ? '保存中…' : '立即保存'}
                </button>
                <button
                  className="annotation-next"
                  disabled={!activeLabel || isSaving || selectedTask?.status === '已暂停'}
                  onClick={() => navigateItem(1)}
                  type="button"
                >
                  保存并下一条
                </button>
                {selectedTask && (
                  <button
                    className="annotation-issue-toggle"
                    disabled={isSaving || selectedTask.status === '已暂停'}
                    onClick={() => void skipCurrentItem()}
                    type="button"
                  >
                    跳过此条
                  </button>
                )}
                <button
                  className="annotation-issue-toggle"
                  onClick={() => {
                    setIssueError('')
                    setIssueStatus('')
                    document.getElementById('issue-description')?.focus()
                  }}
                  type="button"
                >
                  反馈异常
                </button>
              </div>
              <form
                className="annotation-issue-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  void handleIssueReport()
                }}
              >
                <label htmlFor="issue-type">异常类型</label>
                <select
                  id="issue-type"
                  onChange={(event) =>
                    setIssueType(event.target.value as DataItemIssueType)
                  }
                  value={issueType}
                >
                  <option value="数据异常">数据异常</option>
                  <option value="标签疑问">标签疑问</option>
                  <option value="其他">其他</option>
                </select>
                <label htmlFor="issue-description">异常说明</label>
                <textarea
                  id="issue-description"
                  maxLength={500}
                  onChange={(event) => setIssueDescription(event.target.value)}
                  placeholder="描述数据问题或需要确认的标注规则（最多 500 字）"
                  rows={3}
                  value={issueDescription}
                />
                <button
                  className="annotation-issue-submit"
                  disabled={!issueDescription.trim() || isReportingIssue}
                  type="submit"
                >
                  {isReportingIssue ? '提交中…' : '提交反馈'}
                </button>
                {issueError && <p className="form-error" role="alert">{issueError}</p>}
                {issueStatus && <p className="form-success" role="status">{issueStatus}</p>}
              </form>
              {getLabelHistory(selectedItem.fields.label_history).length > 0 && (
                <details className="annotation-history">
                  <summary>标注操作记录</summary>
                  <ol>
                    {getLabelHistory(selectedItem.fields.label_history)
                      .slice()
                      .reverse()
                      .map((entry, index) => (
                        <li key={`${entry.labeled_at}-${index}`}>
                          <span>{entry.label ?? '清除标注'}</span>
                          <span>{entry.labeled_by}</span>
                          <time>{formatDate(entry.labeled_at)}</time>
                        </li>
                      ))}
                  </ol>
                </details>
              )}
            </section>
          )}
        </div>
      )}
    </>
  )
}
