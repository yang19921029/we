# Flask 登录与菜单 API

Python + Flask 的基础 API 示例，使用本地 MySQL 数据库 `we` 保存用户和菜单，登录后通过安全的会话 Cookie 访问菜单。

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app init-admin
flask --app app run --debug
```

MySQL 连接和会话密钥从项目根目录的 `.env` 读取。请勿提交或分享 `.env` 文件；默认 `.gitignore` 已忽略该文件。应用应使用只对 `we` 数据库有权限的 MySQL 账号，不要将管理员密码配置给 Web 服务。

首次部署时，需要先用 MySQL 管理账号创建 `we` 数据库，并给应用账号授予 `we.*` 权限；随后 `init-db` 会初始化用户表、菜单表，并在菜单表为空时写入示例菜单。`init-admin` 会交互式创建或更新登录账号：

```bash
flask --app app init-admin
```

重新运行 `flask --app app init-db` 会将默认菜单更新为“数据标注 / 数据展示列表 / 数据打标”；原算法备案和变更注销菜单会被移除。

数据记录存放在 Elasticsearch，不再从 MySQL 的旧 `data_items` 表读取。设置 Elastic 连接后，运行 `flask --app app init-elastic` 可创建索引并写入示例数据；若索引已经存在，该命令不会覆盖或补写其中的数据。

可通过环境变量配置 Elastic（也可以在项目根目录的 `.env` 中设置）：

```text
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_INDEX=data_items
ELASTICSEARCH_USERNAME=
ELASTICSEARCH_PASSWORD=
ELASTICSEARCH_TIMEOUT=5
```

使用认证时必须同时设置用户名和密码。业务索引文档以 Elastic `_id` 作为数据编号，正文使用 `content` 或 `text` 字段。插入时间优先读取 `inserted_at`、`created_at`、`@timestamp` 或 `timestamp`，兼容历史数据时回退显示 `order_date`；打标时间读取 `labeled_at`，历史数据兼容回退 `updated_at`。新的打标操作会同时写入 `labeled_at` 和 `updated_at`。

生产环境请保护 `.env` 文件，并关闭 Flask debug 模式。

## 接口

### 登录

`POST /api/login`

```json
{"username": "admin", "password": "your-password"}
```

成功响应会设置 HttpOnly 会话 Cookie：

```json
{"code": 0, "message": "登录成功", "data": {"user_id": 1, "username": "admin"}}
```

### 当前登录用户与退出登录

- `GET /api/auth/me`：校验会话并返回当前用户（需要登录）
- `POST /api/logout`：清除当前会话

### 获取一级菜单

`GET /api/menus`（需要登录）

### 获取指定一级菜单下的二级菜单

`GET /api/menus/<menu_id>/children`（需要登录）

例如 `GET /api/menus/2/children`。一级及二级菜单目前从初始化示例数据读取，可按项目需要调整数据库数据。

### 数据展示与标注

- `GET /api/data-items?page=1&page_size=20&label_status=all`：分页获取数据展示列表（需要登录；每页最多 100 条，支持 `all`、`labeled`、`unlabeled` 及具体标注值 `正向`、`负向`、`中性`）
- `GET /api/data-items/<id>`：获取单条数据详情（需要登录）
- `PUT /api/data-items/<id>/label`：保存单条数据的标注（需要登录）

标注请求示例：

```json
{"label": "正向"}
```

当前标注类型为“正向 / 负向 / 中性”。列表筛选支持按标注状态或具体标注值过滤，并显示数据插入时间和打标时间。标注结果、操作人和打标时间会写入对应 Elastic 文档。Elastic 不可用或索引不存在时，API 会返回错误，前端列表、详情和保存失败处均提供重试操作。

## 前端联调

前端位于同级目录 `../we`。初始化 Elastic 后启动本 Flask 服务时使用 5000 端口；Vite 会将 `/api` 请求代理到 `http://127.0.0.1:5000`。账号名由 `init-admin` 命令创建；如果使用登录页面上的手机号登录，请将手机号作为用户名创建。

## 测试

```bash
python -m unittest discover -s tests -v
```

接口测试通过模拟 MySQL 和 Elasticsearch 连接运行，不需要启动数据库服务。
