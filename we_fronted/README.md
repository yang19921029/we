# 前后端联调项目

React + TypeScript + Vite 前端，通过 Flask HTTP API 登录并加载菜单。

登录页路由为 `#/login`，工作台路由为 `#/dashboard`。其他功能页面使用菜单接口返回的 `path` 作为路由，例如 `#/data/list`；数据详情页通过列表中的详情入口打开。一级、二级菜单、工作台快捷入口和浏览器前进/后退会共用这些路由。旧的 `#/home` 地址仍会指向工作台。

页面按职责拆分在 `src/pages/`：`DashboardPage` 是工作台，`MenuFeaturePage` 承载独立菜单功能页，`SystemLayout` 负责公共导航和页面框架。

数据标注菜单包含“数据展示列表”和“数据打标”。列表从 `/api/data-items` 分页读取 Elastic 文档，并可按已标注、未标注或具体标注结果（正向、负向、中性）筛选，同时显示数据插入时间和打标时间；列表中的详情入口通过 `GET /api/data-items/<id>` 查看记录；打标页面通过单选项（正向、负向、中性）并调用 `PUT /api/data-items/<id>/label` 保存分类结果。数据队列展示数据内容。列表加载、详情加载和打标保存失败时都可以重试。

## 前后端联调

前端通过 `/api` 请求 Flask。开发服务器会把这些请求代理到 `http://127.0.0.1:5000`；如后端监听其他地址，可设置 `FLASK_API_TARGET`。

先在终端一启动后端（MySQL 连接配置见后端 README）：

```bash
cd ../we_
flask --app app init-db
flask --app app init-admin
flask --app app run --port 5000
```

在终端二启动前端：

```bash
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
