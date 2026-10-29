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
          <h1>标注工作台</h1>
          <p className="content-subtitle">
            欢迎使用数据标注系统，创建标注任务、管理数据集并跟踪质量。
          </p>
        </div>
        <div className="date-stamp">
          <span className="date-stamp-label">当前身份</span>
          <strong>{username}</strong>
        </div>
      </div>

      <div className="welcome-card">
        <div className="welcome-copy">
          <span className="welcome-label">标注工作流</span>
          <h2>让数据标注更清晰、更高效</h2>
          <p>从数据集准备到任务执行与质量检查，在这里管理完整标注流程。</p>
          <button
            className="welcome-action"
            onClick={() => onOpenMenu('数据标注', '数据打标')}
            type="button"
          >
            开始打标 <span aria-hidden="true">→</span>
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
          <p>快捷进入常用功能</p>
        </div>
        <span className="section-title-note">QUICK ACCESS</span>
      </div>

      <div className="service-grid">
        <button
          className="service-card"
          onClick={() => onOpenMenu('数据标注', '数据展示列表')}
          type="button"
        >
          <span className="service-icon filing-icon" aria-hidden="true">＋</span>
          <span className="service-card-copy">
            <strong>数据展示列表</strong>
            <small>浏览数据内容与当前标注结果</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
        <button
          className="service-card"
          onClick={() => onOpenMenu('数据标注', '数据打标')}
          type="button"
        >
          <span className="service-icon query-icon" aria-hidden="true">⌕</span>
          <span className="service-card-copy">
            <strong>数据打标</strong>
            <small>为数据内容选择分类并保存</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
        <button
          className="service-card"
          onClick={() => onOpenMenu('质量管理', '质检任务')}
          type="button"
        >
          <span className="service-icon guide-icon" aria-hidden="true">文</span>
          <span className="service-card-copy">
            <strong>质检任务</strong>
            <small>查看标注数据的质量检查任务</small>
          </span>
          <span className="service-arrow" aria-hidden="true">↗</span>
        </button>
      </div>

      <div className="dashboard-footer">
        <span>本页面为界面演示，数据仅用于展示布局。</span>
        <span>数据标注管理平台</span>
      </div>
    </>
  )
}
