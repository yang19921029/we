import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { MediaPreview } from './mediaPreview'
import {
  type MultimodalAnnotation,
  type MultimodalAnnotationItem,
} from '../../api'

export function MultimodalAnnotationEditor({
  media,
  annotation,
  label,
  onChange,
}: {
  media: MediaPreview[]
  annotation: MultimodalAnnotation | null
  label: string | null
  onChange: (value: MultimodalAnnotation) => void
}) {
  const [mode, setMode] = useState<MultimodalAnnotationItem['kind']>('bbox')
  const [polygonDraft, setPolygonDraft] = useState<Array<{ x: number; y: number }>>([])
  const [segmentStarts, setSegmentStarts] = useState<Record<string, number>>({})
  const mediaElements = useRef(new Map<string, HTMLMediaElement>())
  const items = annotation?.items ?? []

  function addItem(item: MultimodalAnnotationItem) {
    if (!label) return
    onChange({ items: [...items, { ...item, label }] })
  }

  function pointFromEvent(event: ReactPointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(100, ((event.clientX - bounds.left) / bounds.width) * 100)),
      y: Math.max(0, Math.min(100, ((event.clientY - bounds.top) / bounds.height) * 100)),
    }
  }

  function handleImagePointerUp(
    event: ReactPointerEvent<SVGSVGElement>,
    image: MediaPreview,
    start: { x: number; y: number } | null,
  ) {
    const point = pointFromEvent(event)
    if (mode === 'bbox' && start) {
      if (Math.abs(point.x - start.x) > 0.5 && Math.abs(point.y - start.y) > 0.5) {
        addItem({ kind: 'bbox', label: label ?? '', media_url: image.url, points: [start, point] })
      }
    } else if (mode === 'polygon') {
      setPolygonDraft((current) => [...current, point])
    } else if (mode === 'keypoint') {
      addItem({ kind: 'keypoint', label: label ?? '', media_url: image.url, points: [point] })
    }
  }

  function savePolygon(image: MediaPreview) {
    if (polygonDraft.length < 3 || !label) return
    addItem({
      kind: 'polygon',
      label,
      media_url: image.url,
      points: polygonDraft,
    })
    setPolygonDraft([])
  }

  function saveSegment(image: MediaPreview) {
    const element = mediaElements.current.get(image.url)
    const start = segmentStarts[image.url]
    if (!element || start === undefined || element.currentTime <= start || !label) return
    addItem({
      kind: 'segment',
      label,
      media_url: image.url,
      start,
      end: element.currentTime,
    })
    setSegmentStarts((current) => {
      const next = { ...current }
      delete next[image.url]
      return next
    })
  }

  return (
    <section className="multimodal-annotation-editor" aria-label="多模态标注工具">
      <div className="multimodal-toolbar">
        <label>
          标注工具
          <select
            onChange={(event) => {
              setMode(event.target.value as MultimodalAnnotationItem['kind'])
              setPolygonDraft([])
            }}
            value={mode}
          >
            <option value="bbox">矩形框</option>
            <option value="polygon">多边形分割</option>
            <option value="keypoint">关键点</option>
            <option value="segment">音视频时间片段</option>
          </select>
        </label>
        <span>{label ? `新标注使用标签：${label}` : '请先选择标签，再添加区域或时间片段。'}</span>
      </div>
      {media.map((entry) => {
        const mediaItems = items
          .map((item, index) => ({ item, index }))
          .filter(({ item }) => item.media_url === entry.url)
        return (
          <div className="annotation-media-preview" key={`${entry.name}-${entry.url}`}>
            <span>{entry.name}</span>
            {entry.type === 'image' ? (
              <>
                <div className="multimodal-image-canvas">
                  <img alt={entry.name} loading="lazy" src={entry.url} />
                  <svg
                    aria-label={`${entry.name}标注画布`}
                    onPointerDown={(event) => {
                      if (mode === 'bbox') {
                        const point = pointFromEvent(event)
                        event.currentTarget.setPointerCapture(event.pointerId)
                        event.currentTarget.dataset.start = `${point.x},${point.y}`
                      }
                    }}
                    onPointerUp={(event) => {
                      const rawStart = event.currentTarget.dataset.start
                      const start = rawStart
                        ? rawStart.split(',').map(Number)
                        : null
                      handleImagePointerUp(
                        event,
                        entry,
                        start ? { x: start[0], y: start[1] } : null,
                      )
                      delete event.currentTarget.dataset.start
                    }}
                    role="img"
                    viewBox="0 0 100 100"
                  >
                    {mediaItems.map(({ item, index }) => {
                      const points = item.points ?? []
                      if (item.kind === 'bbox' && points.length === 2) {
                        const [first, second] = points
                        return (
                          <g key={index}>
                            <rect
                              fill="rgba(45, 155, 111, 0.12)"
                              height={Math.abs(second.y - first.y)}
                              stroke="#2d9b6f"
                              strokeWidth="0.5"
                              width={Math.abs(second.x - first.x)}
                              x={Math.min(first.x, second.x)}
                              y={Math.min(first.y, second.y)}
                            />
                            <text fill="#176447" fontSize="3" x={Math.min(first.x, second.x)} y={Math.min(first.y, second.y) - 1}>
                              {item.label}
                            </text>
                          </g>
                        )
                      }
                      if (item.kind === 'polygon' && points.length >= 3) {
                        return (
                          <polygon
                            key={index}
                            fill="rgba(45, 155, 111, 0.12)"
                            points={points.map((point) => `${point.x},${point.y}`).join(' ')}
                            stroke="#2d9b6f"
                            strokeWidth="0.5"
                          />
                        )
                      }
                      if (item.kind === 'keypoint' && points[0]) {
                        return <circle key={index} cx={points[0].x} cy={points[0].y} fill="#d65b57" r="1.5" />
                      }
                      return null
                    })}
                    {mode === 'polygon' && polygonDraft.map((point, index) => (
                      <circle key={index} cx={point.x} cy={point.y} fill="#3869a8" r="1" />
                    ))}
                  </svg>
                </div>
                {mode === 'polygon' && polygonDraft.length > 0 && (
                  <button className="platform-secondary-button" disabled={polygonDraft.length < 3 || !label} onClick={() => savePolygon(entry)} type="button">
                    完成多边形（{polygonDraft.length} 点）
                  </button>
                )}
              </>
            ) : (
              <>
                {entry.type === 'audio' ? (
                  <audio
                    controls
                    preload="metadata"
                    ref={(element) => {
                      if (element) mediaElements.current.set(entry.url, element)
                    }}
                    src={entry.url}
                  />
                ) : (
                  <video
                    controls
                    preload="metadata"
                    ref={(element) => {
                      if (element) mediaElements.current.set(entry.url, element)
                    }}
                    src={entry.url}
                  />
                )}
                {mode === 'segment' && (
                  <div className="multimodal-toolbar">
                    <button
                      className="platform-secondary-button"
                      disabled={!label}
                      onClick={() => {
                        const element = mediaElements.current.get(entry.url)
                        if (element) {
                          setSegmentStarts((current) => ({ ...current, [entry.url]: element.currentTime }))
                        }
                      }}
                      type="button"
                    >
                      记录起点 {segmentStarts[entry.url] === undefined ? '' : `(${segmentStarts[entry.url].toFixed(2)}s)`}
                    </button>
                    <button
                      className="platform-secondary-button"
                      disabled={segmentStarts[entry.url] === undefined || !label}
                      onClick={() => saveSegment(entry)}
                      type="button"
                    >
                      记录终点并添加片段
                    </button>
                  </div>
                )}
              </>
            )}
            {mediaItems.map(({ item, index }) => (
              <div className="multimodal-annotation-row" key={`annotation-${index}`}>
                <span>
                  {item.label} · {item.kind === 'segment' ? `${item.start?.toFixed(2)}s–${item.end?.toFixed(2)}s` : item.kind}
                </span>
                <button
                  aria-label={`删除第 ${index + 1} 个多模态标注`}
                  className="text-link"
                  onClick={() => onChange({ items: items.filter((_, itemIndex) => itemIndex !== index) })}
                  type="button"
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        )
      })}
    </section>
  )
}
