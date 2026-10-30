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

export function formatDate(value: string | null): string {
  if (!value) return '—'
  const datePrefix = /^\d{4}-\d{2}-\d{2}/.exec(value)?.[0]
  if (datePrefix) return datePrefix

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(0, 10)
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
) {
  const [items, setItems] = useState<DataItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void getDataItems(
      page,
      pageSize,
      labelStatus,
      controller.signal,
      datasetId,
      searchText,
      sortBy,
      taskId,
    )
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
  }, [datasetId, labelStatus, loadAttempt, onSessionExpired, page, pageSize, searchText, sortBy, taskId])

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

  return { items, total, isLoading, error, retry, saveLabel }
}
