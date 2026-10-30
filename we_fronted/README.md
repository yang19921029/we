# 前后端联调项目

React + TypeScript + Vite 前端，通过 Flask HTTP API 登录并加载菜单。

登录页路由为 `#/login`，工作台路由为 `#/dashboard`。其他功能页面使用菜单接口返回的 `path` 作为路由，例如 `#/data/list`；数据详情页通过列表中的详情入口打开。一级、二级菜单、工作台快捷入口和浏览器前进/后退会共用这些路由。旧的 `#/home` 地址仍会指向工作台。

页面按功能拆分在 `src/pages/`：`DashboardPage` 是工作台；`pages/platform/` 按数据集、项目、任务、标签、质检、统计、导出、用户和审计页面分别组织；`pages/data-items/` 分离数据列表、详情、标注工作台及多模态标注组件。原 `PlatformPages` 和 `DataItemsPages` 文件保留为导出入口，路由调用无需调整。共享页面组件和纯工具函数分别放在独立模块中。全局样式按登录页、系统框架、数据标注和管理页面拆分在 `src/styles/`，继续由 `App.css` 按原有顺序汇总。

一期功能包含组织 → 项目 → 数据集 → 任务管理、CSV/JSON/JSONL 导入、数据集筛选与搜索、任务创建/分配/进度跟踪、可版本化标签体系和按任务标注。标注工作台支持自动保存、撤销/重做、快捷键、跳过/暂停、规范查看和异常反馈；媒体数据可进行图像矩形框/多边形/关键点标注及音视频时间片段标注。标注结果、审核结果与业务配置的变更会保留操作记录。质量审核、用户角色、统计看板和 JSONL/CSV 导出使用后端数据，不使用静态示例指标。

数据导入限制为每文件 10 MB、每次最多 5000 条；每个任务最多包含 10000 条数据；单次导出最多 10000 条。默认启用手机号、邮箱和身份证号脱敏，可通过后端 `MASK_SENSITIVE_DATA=false` 关闭（仅在确有权限依据时配置）。

当前版本已覆盖 P0 核心流程、主要 P1 管理能力，以及基础自动质检、低置信度排序、按工作量分配和逾期任务 SLA 统计等 P2 能力。AI 预标注可通过后端配置接入 DeepSeek `deepseek-chat`，默认关闭；启用后只发送经默认 PII 脱敏的文本，建议需人工确认。项目成员隔离作用于项目下的数据集、任务、标注、审核、统计、质检与导入导出；超级管理员/项目管理员按已确认策略拥有跨项目权限。成本统计仍等待确定计费规则。

## 前后端联调

前端通过 `/api` 请求 Flask。开发服务器会把这些请求代理到 `http://127.0.0.1:5000`；如后端监听其他地址，可设置 `FLASK_API_TARGET`。

先在终端一启动后端（MySQL 连接配置见后端 README）：

```bash
cd we_backed
flask --app app init-db
flask --app app init-admin
flask --app app run --port 5000
```

在终端二启动前端：

```bash
cd we_fronted
npm install
npm run dev
```

登录页使用“账号 / 手机号”字段。通过 `init-admin` 创建账号时，可将手机号作为用户名。登录成功后，服务端会设置会话 Cookie；前端请求会携带此 Cookie，并从接口加载一级和二级菜单。

接口代理目标也可自定义：

```bash
FLASK_API_TARGET=http://127.0.0.1:5001 npm run dev
```

构建与静态检查：

```bash
npm run build
npm run lint
```

## 开发工具说明

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
