import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  getMenuSections,
  getNotifications,
  markNotificationRead,
  updateOnlinePresence,
  type AppNotification,
  type MenuSection,
} from '../api'
import { normalizePath, navigateTo } from '../routing'
import { formatDate } from '../dateFormat'
import DashboardPage from './DashboardPage'
import {
  DataDetailPage,
  DataLabelPage,
  DataListPage,
} from './DataItemsPages'
import {
  DatasetManagementPage,
  DataExportPage,
  AuditLogPage,
  LabelSchemaPage,
  QualityManagementPage,
  QualityReviewPage,
  ProjectManagementPage,
  StatisticsPage,
  TaskManagementPage,
  UserManagementPage,
} from './PlatformPages'
import MenuFeaturePage from './MenuFeaturePage'
import { AccountSecurityModal } from './platform/AccountSecurityModal'

function getDataItemId(route: string): string {
  const encodedId = route.slice('/data/detail/'.length)
  try {
    return decodeURIComponent(encodedId)
  } catch (error) {
    if (!(error instanceof URIError)) throw error
    return encodedId
  }
}

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  )
}

export default function SystemLayout({
  onLogout,
  onSessionExpired,
  route,
  role,
  username,
}: {
  onLogout: () => Promise<void>
  onSessionExpired: () => void
  route: string
  role: string
  username: string
}) {
  const [menuSections, setMenuSections] = useState<MenuSection[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [menuError, setMenuError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [logoutError, setLogoutError] = useState('')
  const [isAccountSecurityOpen, setIsAccountSecurityOpen] = useState(false)
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false)
  const [onlineUserCount, setOnlineUserCount] = useState<number | null>(null)
  const [presenceError, setPresenceError] = useState('')
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [notificationError, setNotificationError] = useState('')
  const [isNotificationOpen, setIsNotificationOpen] = useState(false)
  const accountMenuRef = useRef<HTMLDivElement>(null)

  const canonicalRoute = route === '/tasks/assign'
    ? '/tasks/list'
    : route === '/operations/security'
      ? '/operations/complaints'
      : route
  const visibleMenuSections = menuSections.map((section) => ({
    ...section,
    items: section.items.filter(
      (item) =>
        normalizePath(item.path) !== '/tasks/assign' &&
        normalizePath(item.path) !== '/operations/security',
    ),
  }))
  const isDataDetailRoute = route.startsWith('/data/detail/')
  const taskRouteMatch = /^\/data\/label\/(\d+)$/.exec(route)
  const routeMatch = visibleMenuSections
    .flatMap((section) =>
      section.items.map((item) => ({ section, item })),
    )
    .find(
      ({ item }) =>
        normalizePath(item.path) === canonicalRoute ||
        (isDataDetailRoute && normalizePath(item.path) === '/data/list') ||
        (taskRouteMatch && normalizePath(item.path) === '/data/label'),
    )
  const parentMatch = visibleMenuSections.find(
    (section) => normalizePath(section.path) === canonicalRoute,
  )
  const selectedSection = routeMatch?.section ?? parentMatch
  const activeItem = routeMatch?.item ?? parentMatch?.items[0]
  const activeSection = selectedSection?.name ?? ''

  useEffect(() => {
    if (!isAccountMenuOpen) return

    function handlePointerDown(event: PointerEvent) {
      if (
        event.target instanceof Node &&
        !accountMenuRef.current?.contains(event.target)
      ) {
        setIsAccountMenuOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setIsAccountMenuOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isAccountMenuOpen])

  useEffect(() => {
    let active = true
    async function refreshOnlineUsers() {
      try {
        const presence = await updateOnlinePresence()
        if (active) {
          setOnlineUserCount(presence.online_users)
          setPresenceError('')
        }
      } catch (error) {
        if (!active) return
        if (error instanceof ApiError && error.status === 401) {
          onSessionExpired()
          return
        }
        setOnlineUserCount(null)
        setPresenceError(error instanceof Error ? error.message : '在线人数获取失败。')
      }
    }

    void refreshOnlineUsers()
    const timer = window.setInterval(() => void refreshOnlineUsers(), 60_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [onSessionExpired])

  useEffect(() => {
    let active = true
    async function refreshNotifications() {
      try {
        const result = await getNotifications()
        if (active) {
          setNotifications(result.items)
          setNotificationError('')
        }
      } catch (error) {
        if (!active) return
        if (error instanceof ApiError && error.status === 401) {
          onSessionExpired()
          return
        }
        setNotificationError(error instanceof Error ? error.message : '通知加载失败。')
      }
    }

    void refreshNotifications()
    const timer = window.setInterval(() => void refreshNotifications(), 60_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [onSessionExpired, username])

  useEffect(() => {
    const controller = new AbortController()
    void getMenuSections(controller.signal)
      .then(setMenuSections)
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) {
          onSessionExpired()
          return
        }
        setMenuError(error instanceof Error ? error.message : '菜单加载失败。')
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [loadAttempt, onSessionExpired])

  function retryMenuLoad() {
    setIsLoading(true)
    setMenuError('')
    setLoadAttempt((attempt) => attempt + 1)
  }

  function selectSection(section: MenuSection) {
    const visibleItems = section.items.filter(
      (item) =>
        normalizePath(item.path) !== '/tasks/assign' &&
        normalizePath(item.path) !== '/operations/security',
    )
    navigateTo(visibleItems[0]?.path ?? section.path)
  }

  function selectMenuItem(sectionLabel: string, itemLabel: string) {
    const section = visibleMenuSections.find(
      (menuSection) => menuSection.name === sectionLabel,
    )
    const item = section?.items.find(
      (menuItem) => menuItem.name === itemLabel,
    )
    if (item) navigateTo(item.path)
  }

  async function handleLogout() {
    setLogoutError('')
    try {
      await onLogout()
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : '退出登录失败。')
    }
  }

  return (
    <main className="system-shell">
      <header className="system-header">
        <a
          aria-label="数据标注管理平台标注工作台"
          className="system-brand"
          href="#/dashboard"
          onClick={(event) => {
            event.preventDefault()
            navigateTo('/dashboard')
          }}
        >
          <BrandMark />
          <span className="system-brand-name">数据标注管理平台</span>
          <span className="system-brand-divider" />
          <span className="system-name">数据标注系统</span>
        </a>

        <div className="header-tools">
          <div className="notification-menu">
            <button
              aria-expanded={isNotificationOpen}
              aria-label={`通知，${notifications.filter((notification) => !notification.is_read).length} 条未读`}
              className="notification-trigger"
              onClick={() => setIsNotificationOpen((open) => !open)}
              type="button"
            >
              通知
              {notifications.some((notification) => !notification.is_read) && (
                <span className="notification-count">
                  {notifications.filter((notification) => !notification.is_read).length}
                </span>
              )}
            </button>
            {isNotificationOpen && (
              <div aria-label="站内通知" className="notification-dropdown">
                {notificationError && (
                  <p className="platform-error" role="alert">{notificationError}</p>
                )}
                {notifications.length === 0 ? (
                  <p className="data-empty">暂无通知。</p>
                ) : notifications.map((notification) => (
                  <button
                    className={`notification-item${notification.is_read ? '' : ' is-unread'}`}
                    key={notification.id}
                    onClick={async () => {
                      try {
                        if (!notification.is_read) {
                          await markNotificationRead(notification.id)
                          setNotifications((current) => current.map((item) =>
                            item.id === notification.id ? { ...item, is_read: true } : item,
                          ))
                        }
                        setIsNotificationOpen(false)
                        if (notification.link) navigateTo(notification.link)
                      } catch (error) {
                        setNotificationError(error instanceof Error ? error.message : '通知更新失败。')
                      }
                    }}
                    type="button"
                  >
                    <strong>{notification.title}</strong>
                    <span>{notification.body}</span>
                    <time>{formatDate(notification.created_at)}</time>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="account-menu" ref={accountMenuRef}>
            <button
              aria-expanded={isAccountMenuOpen}
              aria-haspopup="menu"
              aria-label={`账号菜单：${username}；当前在线用户 ${
                onlineUserCount === null ? '暂不可用' : onlineUserCount
              } 人；账号权限：${role || '未设置'}`}
              className="account-menu-trigger"
              onClick={() => setIsAccountMenuOpen((open) => !open)}
              type="button"
            >
              <span
                aria-hidden="true"
                className="user-avatar online-user-count"
                title={presenceError || '最近 5 分钟内有活动的去重账号数'}
              >
                {onlineUserCount ?? '—'}
              </span>
              <span className="user-name">{username}</span>
              <span className="user-role">{role || '权限未设置'}</span>
              <span aria-hidden="true" className="account-menu-chevron">▾</span>
            </button>
            {isAccountMenuOpen && (
              <div className="account-menu-dropdown" id="account-menu-items" role="menu">
                <button
                  className="account-menu-item"
                  onClick={() => {
                    setIsAccountMenuOpen(false)
                    setIsAccountSecurityOpen(true)
                  }}
                  role="menuitem"
                  type="button"
                >
                  账号安全
                </button>
              </div>
            )}
          </div>
          <button className="logout-button" onClick={handleLogout} type="button">
            退出登录
          </button>
        </div>
      </header>

      {logoutError && (
        <p className="api-error logout-error" role="alert">
          退出失败：{logoutError}
        </p>
      )}
      {isAccountSecurityOpen && (
        <AccountSecurityModal onClose={() => setIsAccountSecurityOpen(false)} />
      )}

      <nav aria-label="一级菜单" className="primary-nav">
        {visibleMenuSections.map((section) => (
          <button
            aria-current={activeSection === section.name ? 'page' : undefined}
            className={`primary-nav-item${activeSection === section.name ? ' is-active' : ''}`}
            key={section.id}
            onClick={() => selectSection(section)}
            type="button"
          >
            {section.name}
          </button>
        ))}
      </nav>

      <div className="system-body">
        <aside aria-label="二级菜单" className="side-nav">
          <div className="side-nav-heading">
            <span className="side-nav-overline">NAVIGATION</span>
            <span>{selectedSection?.name ?? '菜单'}</span>
          </div>
          <div className="side-nav-items">
            {(selectedSection?.items ?? []).map((item) => (
              <button
                aria-current={activeItem?.id === item.id ? 'page' : undefined}
                className={`side-nav-item${activeItem?.id === item.id ? ' is-active' : ''}`}
                key={item.id}
                onClick={() => navigateTo(item.path)}
                type="button"
              >
                <span className="side-nav-indicator" />
                {item.name}
              </button>
            ))}
            {!isLoading && !menuError && selectedSection?.items.length === 0 && (
              <p className="menu-empty">暂无二级菜单</p>
            )}
          </div>
          <div className="sidebar-help">
            <span className="help-icon" aria-hidden="true">?</span>
            <span>需要帮助？</span>
            <span className="help-detail">查看标注规范</span>
          </div>
        </aside>

        <section aria-label="菜单内容" className="workspace">
          {isLoading ? (
            <p className="api-message" role="status">正在加载菜单…</p>
          ) : menuError ? (
            <div className="api-error" role="alert">
              <p>菜单加载失败：{menuError}</p>
              <button
                className="welcome-action"
                onClick={retryMenuLoad}
                type="button"
              >
                重试
              </button>
            </div>
          ) : !selectedSection ? (
            <div className="api-message" role="status">
              <h1>页面不存在</h1>
              <p>当前地址未对应到已配置的功能菜单。</p>
              <button
                className="welcome-action"
                onClick={() => navigateTo('/dashboard')}
                type="button"
              >
                返回工作台
              </button>
            </div>
          ) : !activeItem ? (
            <>
              <div className="content-breadcrumb">
                <span>工作台</span>
                <span className="breadcrumb-divider">/</span>
                <span>{selectedSection.name}</span>
              </div>
              <p className="api-message">当前一级菜单暂无二级菜单。</p>
            </>
          ) : (
            <>
              <div className="content-breadcrumb">
                <span>工作台</span>
                <span className="breadcrumb-divider">/</span>
                <span>{activeSection}</span>
                {activeItem.name !== '标注工作台' && (
                  <>
                    <span className="breadcrumb-divider">/</span>
                    <span className="breadcrumb-current">{activeItem.name}</span>
                  </>
                )}
              </div>
              {route === '/dashboard' || activeItem.name === '标注工作台' ? (
                <DashboardPage
                  availableMenus={visibleMenuSections}
                  onOpenMenu={selectMenuItem}
                  username={username}
                />
              ) : isDataDetailRoute ? (
                <DataDetailPage
                  itemId={getDataItemId(route)}
                  key={route}
                  onSessionExpired={onSessionExpired}
                />
              ) : route === '/data/list' ? (
                <DataListPage
                  onOpenDetails={(itemId) =>
                    navigateTo(`/data/detail/${encodeURIComponent(itemId)}`)
                  }
                  onSessionExpired={onSessionExpired}
                />
              ) : route === '/data/label' ? (
                <DataLabelPage key="annotation-all" onSessionExpired={onSessionExpired} />
              ) : taskRouteMatch ? (
                <DataLabelPage
                  initialTaskId={Number(taskRouteMatch[1])}
                  key={`annotation-task-${taskRouteMatch[1]}`}
                  onSessionExpired={onSessionExpired}
                />
              ) : route === '/datasets' ? (
                <DatasetManagementPage onSessionExpired={onSessionExpired} />
              ) : route === '/projects' ? (
                <ProjectManagementPage onSessionExpired={onSessionExpired} role={role} />
              ) : canonicalRoute === '/tasks/list' ? (
                <TaskManagementPage
                  onOpenTask={(taskId) => navigateTo(`/data/label/${taskId}`)}
                  onSessionExpired={onSessionExpired}
                  username={username}
                />
              ) : route === '/labels' || route === '/labels/versions' ? (
                <LabelSchemaPage onSessionExpired={onSessionExpired} />
              ) : route === '/operations/reports' ? (
                <QualityReviewPage onSessionExpired={onSessionExpired} />
              ) : route === '/operations/security' || route === '/operations/complaints' ? (
                <QualityManagementPage
                  onSessionExpired={onSessionExpired}
                  role={role}
                  route={route}
                />
              ) : route === '/analytics' ? (
                <StatisticsPage onSessionExpired={onSessionExpired} />
              ) : route === '/data/export' ? (
                <DataExportPage onSessionExpired={onSessionExpired} />
              ) : route === '/users' ? (
                <UserManagementPage onSessionExpired={onSessionExpired} />
              ) : route === '/audit-logs' ? (
                <AuditLogPage onSessionExpired={onSessionExpired} />
              ) : (
                <MenuFeaturePage section={selectedSection} item={activeItem} />
              )}
            </>
          )}
        </section>
      </div>
    </main>
  )
}
