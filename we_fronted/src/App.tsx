import { useCallback, useEffect, useState } from 'react'
import { ApiError, getCurrentUser, logout } from './api'
import { getHashPath, LOGIN_PATH, navigateTo, normalizePath } from './routing'
import LoginPage from './pages/LoginPage'
import SystemLayout from './pages/SystemLayout'
import './App.css'

function App() {
  const [route, setRoute] = useState(getHashPath)
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [isCheckingSession, setIsCheckingSession] = useState(
    () => getHashPath() !== LOGIN_PATH,
  )
  const [username, setUsername] = useState('')
  const [sessionError, setSessionError] = useState('')
  const [sessionAttempt, setSessionAttempt] = useState(0)

  useEffect(() => {
    function syncRoute() {
      const nextRoute = getHashPath()
      setRoute(nextRoute)
      if (nextRoute === LOGIN_PATH) {
        setIsLoggedIn(false)
        setIsCheckingSession(false)
        setUsername('')
        setSessionError('')
      } else if (!isLoggedIn) {
        setIsCheckingSession(true)
        setSessionError('')
      }
    }

    window.addEventListener('hashchange', syncRoute)
    return () => window.removeEventListener('hashchange', syncRoute)
  }, [isLoggedIn])

  useEffect(() => {
    if (route === LOGIN_PATH || isLoggedIn) return

    const controller = new AbortController()
    void getCurrentUser(controller.signal)
      .then((user) => {
        setUsername(user.username)
        setIsLoggedIn(true)
        setIsCheckingSession(false)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) {
          navigateTo(LOGIN_PATH)
          return
        }
        setSessionError(
          error instanceof Error ? error.message : '登录状态校验失败。',
        )
        setIsCheckingSession(false)
      })

    return () => controller.abort()
  }, [isLoggedIn, route, sessionAttempt])

  const handleLogin = useCallback((nextUsername: string) => {
    setUsername(nextUsername)
    setSessionError('')
    setIsCheckingSession(true)
    setSessionAttempt((attempt) => attempt + 1)
    navigateTo('/dashboard')
  }, [])

  const handleLogout = useCallback(async () => {
    await logout()
    setIsLoggedIn(false)
    navigateTo(LOGIN_PATH)
  }, [])

  const handleSessionExpired = useCallback(() => {
    setIsLoggedIn(false)
    navigateTo(LOGIN_PATH)
  }, [])

  if (isCheckingSession) {
    return (
      <main className="session-check" role="status">
        正在验证登录状态…
      </main>
    )
  }

  return isLoggedIn ? (
    <SystemLayout
      onLogout={handleLogout}
      onSessionExpired={handleSessionExpired}
      route={normalizePath(route)}
      username={username}
    />
  ) : (
    <LoginPage onLogin={handleLogin} initialNotice={sessionError} />
  )
}

export default App
