export function DataPageHeading({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <div className="content-heading data-page-heading">
      <div>
        <p className="content-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="content-subtitle">{description}</p>
      </div>
    </div>
  )
}

export function DataLoadState({
  isLoading,
  error,
  onRetry,
}: {
  isLoading: boolean
  error: string
  onRetry: () => void
}) {
  if (isLoading) {
    return <p className="api-message" role="status">正在加载数据…</p>
  }
  if (error) {
    return (
      <div className="api-error" role="alert">
        <p>数据加载失败：{error}</p>
        <button className="welcome-action" onClick={onRetry} type="button">
          重试
        </button>
      </div>
    )
  }
  return null
}
