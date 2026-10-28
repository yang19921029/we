export default function DashboardPage({
  onOpenMenu,
  username,
}: {
  onOpenMenu: (section: string, item: string) => void
  username: string
}) {
  return (
    <>
      <div className="content-heading">
        <div>
          <p className="content-eyebrow">OVERVIEW</p>
          <h1>工作台</h1>
          <p className="content-subtitle">
            欢迎使用互联网信息服务算法备案系统，请选择需要办理的业务。
          </p>
        </div>
        <div className="date-stamp">
          <span className="date-stamp-label">当前身份</span>
          <strong>{username}</strong>
        </div>
      </div>

      <div className="welcome-card">
        <div className="welcome-copy">
          <span className="welcome-label">服务指引</span>
          <h2>让备案办理更清晰、更高效</h2>
          <p>从提交备案到信息维护，在这里管理您的算法服务备案事项。</p>
          <button
            className="welcome-action"
            onClick={() => onOpenMenu('算法备案', '算法信息服务备案')}
            type="button"
          >
            开始办理 <span aria-hidden="true">→</span>
          </button>
        </div>
        <div aria-hidden="true" className="welcome-art">
          <div className="art-orbit art-orbit-one" />
          <div className="art-orbit art-orbit-two" />
          <div className="art-document">
            <span />
            <span />
            <span />
            <i />
          </div>
          <div className="art-check">✓</div>
        </div>
      </div>

      <div className="section-title-row">
        <div>
          <h2>常用服务</h2>
          <p>快捷进入常用业务</p>
        </div>
        <span className="section-title-note">QUICK ACCESS</span>
      </div>

      <div className="service-grid">
        <button
          className="service-card"
          onClick={() => onOpenMenu('算法备案', '算法信息服务备案')}
          type="button"
        >
          <span className="service-icon filing-icon" aria-hidden="true">＋</span>
          <span className="service-card-copy">
            <strong>算法信息服务备案</strong>
            <small>提交新的算法备案申请</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
        <button
          className="service-card"
          onClick={() => onOpenMenu('算法备案', '算法备案信息查询')}
          type="button"
        >
          <span className="service-icon query-icon" aria-hidden="true">⌕</span>
          <span className="service-card-copy">
            <strong>备案信息查询</strong>
            <small>查询备案信息与办理进度</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
        <button
          className="service-card"
          onClick={() => onOpenMenu('政策法规', '办事指南')}
          type="button"
        >
          <span className="service-icon guide-icon" aria-hidden="true">文</span>
          <span className="service-card-copy">
            <strong>办事指南</strong>
            <small>了解备案流程和办理要求</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
      </div>

      <div className="dashboard-footer">
        <span>本页面为界面演示，数据仅用于展示布局。</span>
        <span>算法备案服务平台</span>
      </div>
    </>
  )
}
