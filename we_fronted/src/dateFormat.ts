export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'

  const datePrefix = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (datePrefix) {
    const [, year, month, day] = datePrefix
    const parsedDate = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)))
    if (
      parsedDate.getUTCFullYear() === Number(year) &&
      parsedDate.getUTCMonth() === Number(month) - 1 &&
      parsedDate.getUTCDate() === Number(day)
    ) {
      return `${year}-${month}-${day}`
    }
  }

  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(0, 10)
}
