export const LOGIN_PATH = '/login'

export function normalizePath(path: string): string {
  const pathname = path.startsWith('#') ? path.slice(1) : path
  const withLeadingSlash = pathname.startsWith('/')
    ? pathname
    : `/${pathname}`
  return withLeadingSlash.replace(/\/+$/, '') || '/'
}

export function getHashPath(): string {
  const hash = window.location.hash
  const path = hash.startsWith('#/') ? normalizePath(hash) : LOGIN_PATH
  return path === '/home' ? '/dashboard' : path
}

export function navigateTo(path: string): void {
  const nextPath = normalizePath(path)
  if (normalizePath(window.location.hash || LOGIN_PATH) !== nextPath) {
    window.location.hash = nextPath
  }
}
