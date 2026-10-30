import { ApiError } from '../api'

export function handlePageError(
  error: unknown,
  onSessionExpired: () => void,
  fallback: string,
): string {
  if (error instanceof ApiError && error.status === 401) {
    onSessionExpired()
    return ''
  }
  return error instanceof Error ? error.message : fallback
}
