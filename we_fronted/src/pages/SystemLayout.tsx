import { useEffect, useState } from 'react'
import { ApiError, getMenuSections, type MenuSection } from '../api'
import { normalizePath, navigateTo } from '../routing'
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
  QualityReviewPage,
  ProjectManagementPage,
  StatisticsPage,
  TaskManagementPage,
  UserManagementPage,
} from './PlatformPages'
import MenuFeaturePage from './MenuFeaturePage'

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

  const isDataDetailRoute = route.startsWith('/data/detail/')
  const taskRouteMatch = /^\/data\/label\/(\d+)$/.exec(route)
  const routeMatch = menuSections
    .flatMap((section) =>
      section.items.map((item) => ({ section, item })),
    )
    .find(
      ({ item }) =>
        normalizePath(item.path) === route ||
        (isDataDetailRoute && normalizePath(item.path) === '/data/list') ||
        (taskRouteMatch && normalizePath(item.path) === '/data/label'),
    )
  const parentMatch = menuSections.find(
    (section) => normalizePath(section.path) === route,
  )
  const selectedSection = routeMatch?.section ?? parentMatch
  const activeItem = routeMatch?.item ?? parentMatch?.items[0]
  const activeSection = selectedSection?.name ?? ''

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
    navigateTo(section.items[0]?.path ?? section.path)
  }

  function selectMenuItem(sectionLabel: string, itemLabel: string) {
    const section = menuSections.find(
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
          <span className="environment-tag">
            <span className="demo-dot" />
            已连接
          </span>
          <span className="header-separator" />
          <span className="user-avatar">{username.slice(0, 1)}</span>
          <span className="user-name">{username}</span>
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

      <nav aria-label="一级菜单" className="primary-nav">
        {menuSections.map((section) => (
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
              ) : route === '/tasks/list' || route === '/tasks/assign' ? (
                <TaskManagementPage
                  onOpenTask={(taskId) => navigateTo(`/data/label/${taskId}`)}
                  onSessionExpired={onSessionExpired}
                  username={username}
                />
              ) : route === '/labels' || route === '/labels/versions' ? (
                <LabelSchemaPage onSessionExpired={onSessionExpired} />
              ) : route.startsWith('/operations/') ? (
                <QualityReviewPage onSessionExpired={onSessionExpired} />
              ) : route === '/analytics' ? (
                <StatisticsPage onSessionExpired={onSessionExpired} />
              ) : route === '/data/export' ? (
                <DataExportPage />
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
