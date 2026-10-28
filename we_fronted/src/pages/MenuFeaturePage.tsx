import type { MenuRecord, MenuSection } from '../api'

export default function MenuFeaturePage({
  section,
  item,
}: {
  section: MenuSection
  item: MenuRecord
}) {
  return (
    <>
      <div className="content-heading section-page-heading">
        <div>
          <p className="content-eyebrow">{section.name.toUpperCase()}</p>
          <h1>{item.name}</h1>
          <p className="content-subtitle">进入「{item.name}」查看并办理相关业务。</p>
        </div>
      </div>
      <div className="section-overview">
        <div className="section-overview-copy">
          <span className="overview-icon" aria-hidden="true">i</span>
          <div>
            <strong>业务办理说明</strong>
            <p>
              您正在查看「{item.name}」功能。业务数据和在线办理尚未接入。
            </p>
          </div>
        </div>
        <span className="preview-tag">演示页面</span>
      </div>
      <div className="section-title-row">
        <div>
          <h2>办理流程</h2>
          <p>按步骤准备材料并提交申请</p>
        </div>
        <span className="section-title-note">HOW IT WORKS</span>
      </div>
      <div className="process-card">
        {['阅读办事指南', '准备备案材料', '填写并提交信息', '查看办理进度'].map(
          (step, index) => (
            <div className="process-step" key={step}>
              <span className="process-number">{`0${index + 1}`}</span>
              <strong>{step}</strong>
              {index < 3 && (
                <span className="process-connector" aria-hidden="true">→</span>
              )}
            </div>
          ),
        )}
      </div>
      <div className="empty-records">
        <span className="empty-record-icon" aria-hidden="true">▤</span>
        <strong>暂无演示数据</strong>
        <p>接入业务服务后，此处将展示相关备案记录。</p>
      </div>
      <div className="dashboard-footer">
        <span>本页面为界面演示，数据仅用于展示布局。</span>
        <span>算法备案服务平台</span>
      </div>
    </>
  )
}
