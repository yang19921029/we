export function PageTitle({
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
