import { useEffect, useId, type ReactNode } from 'react'

export function PlatformModal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const titleId = useId()

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div
      className="platform-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        aria-labelledby={titleId}
        aria-modal="true"
        className="platform-modal"
        role="dialog"
      >
        <header className="platform-modal-header">
          <h2 id={titleId}>{title}</h2>
          <button
            aria-label="关闭弹窗"
            className="platform-modal-close"
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </header>
        <div className="platform-modal-content">{children}</div>
      </section>
    </div>
  )
}
