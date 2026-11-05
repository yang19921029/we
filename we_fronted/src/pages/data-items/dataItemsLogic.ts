import { useCallback, useEffect, useState } from 'react'
import {
  ApiError,
  getDataItems,
  saveDataItemLabel,
  type LabelStatusFilter,
  type DataItem,
  type DataLabel,
  type LabelHistoryEntry,
  type MultimodalAnnotation,
} from '../../api'
export { formatDate } from '../../dateFormat'

export const LABEL_OPTIONS: DataLabel[] = ['正向', '中性', '负向']

export const PAGE_SIZE = 20

export const ANNOTATION_PAGE_SIZE = 100

export function isDataLabel(label: string | null | undefined): label is DataLabel {
  return Boolean(label && label.trim())
}

export function getLabelHistory(value: unknown): LabelHistoryEntry[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (entry): entry is LabelHistoryEntry =>
      typeof entry === 'object' &&
      entry !== null &&
      'label' in entry &&
      (entry.label === null ||
        (typeof entry.label === 'string' && entry.label.length > 0)) &&
      'labeled_by' in entry &&
      typeof entry.labeled_by === 'string' &&
      'labeled_at' in entry &&
      typeof entry.labeled_at === 'string',
  )
}

export function useDataItems(
  onSessionExpired: () => void,
  page: number,
  pageSize: number,
  labelStatus: LabelStatusFilter,
  datasetId?: number,
  taskId?: number,
  searchText = '',
  sortBy: 'newest' | 'uncertain' = 'newest',
  after?: string,
  pitId?: string,
) {
  const [items, setItems] = useState<DataItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [responsePitId, setResponsePitId] = useState<string | null>(null)
  const [responsePage, setResponsePage] = useState<number | null>(null)
  const [responseKey, setResponseKey] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const requestKey = JSON.stringify([
    page,
    pageSize,
    labelStatus,
    datasetId,
    taskId,
    searchText,
    sortBy,
    after,
    pitId,
    loadAttempt,
  ])

  useEffect(() => {
    const controller = new AbortController()
    setIsLoading(true)
    setError('')
    void getDataItems(
      page,
      pageSize,
      labelStatus,
      controller.signal,
      datasetId,
      searchText,
      sortBy,
      taskId,
      after,
      pitId,
    )
      .then((result) => {
        setItems(result.items)
        setTotal(result.total)
        setNextCursor(result.next_cursor)
        setResponsePitId(result.pit_id)
        setResponsePage(result.page)
        setResponseKey(requestKey)
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
  }, [after, datasetId, labelStatus, loadAttempt, onSessionExpired, page, pageSize, pitId, requestKey, searchText, sortBy, taskId])

  const saveLabel = useCallback(async (
    itemId: string,
    label: DataLabel | null,
    annotation?: MultimodalAnnotation,
  ) => {
    try {
      const result = await saveDataItemLabel(itemId, label, taskId, annotation)
      setItems((currentItems) =>
        currentItems.map((item) =>
          item.id === result.id
            ? {
                ...item,
                label: result.label,
                labeled_by: result.labeled_by,
                labeled_at: result.labeled_at,
                ...(annotation !== undefined ? { annotation } : {}),
                fields: {
                  ...item.fields,
                  ...(result.history_entry
                    ? {
                        label_history: [
                          ...getLabelHistory(item.fields.label_history),
                          result.history_entry,
                        ],
                      }
                    : {}),
                  ...(annotation !== undefined ? { annotation } : {}),
                },
              }
            : item,
        ),
      )
      return result
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        onSessionExpired()
      }
      throw cause
    }
  }, [onSessionExpired, taskId])

  function retry() {
    setError('')
    setIsLoading(true)
    setLoadAttempt((attempt) => attempt + 1)
  }

  return {
    items,
    total,
    isLoading,
    error,
    retry,
    saveLabel,
    nextCursor,
    pitId: responsePitId,
    responsePage,
    requestKey,
    responseKey,
  }
}
