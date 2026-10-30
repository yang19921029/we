# 标注平台 Flask API

Python + Flask 的基础 API 示例，使用本地 MySQL 数据库 `we` 保存用户和菜单，登录后通过安全的会话 Cookie 访问菜单。

## 代码结构

- `app.py`：Flask 应用工厂、环境配置、扩展连接与 CLI 命令。
- `database.py`：数据库创建及幂等表结构初始化。
- `routes/`：按认证、项目/数据集、标签体系、任务、管理质检、数据查询和标注拆分的 API 路由；`register_routes()` 统一注册。

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

升级代码后请重新运行 `flask --app app init-db`。该命令会幂等创建组织、项目、数据集、标签体系、任务、任务数据、审计日志等表，并为旧数据集补上默认项目归属、补齐默认菜单和旧用户表中的角色字段；已有用户保留原账号，角色默认为“项目管理员”。

数据记录存放在 Elasticsearch，不再从 MySQL 的旧 `data_items` 表读取。设置 Elastic 连接后，运行 `flask --app app init-elastic` 可创建索引并写入示例数据；若索引已经存在，该命令不会覆盖或补写其中的数据。

可通过环境变量配置 Elastic（也可以在项目根目录的 `.env` 中设置）：

```text
ELASTICSEARCH_URL=http://127.0.0.1:9200
ELASTICSEARCH_INDEX=data_items
ELASTICSEARCH_USERNAME=
ELASTICSEARCH_PASSWORD=
ELASTICSEARCH_TIMEOUT=5
AI_ENABLED=true
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-chat
AI_API_KEY=
AI_TIMEOUT=30
```

使用认证时必须同时设置用户名和密码。业务索引文档以 Elastic `_id` 作为数据编号，正文使用 `content` 或 `text` 字段。插入时间优先读取 `inserted_at`、`created_at`、`@timestamp` 或 `timestamp`，兼容历史数据时回退显示 `order_date`；打标时间读取 `labeled_at`，历史数据兼容回退 `updated_at`。新的打标操作会同时写入 `labeled_at` 和 `updated_at`。

AI 预标注默认关闭。启用 DeepSeek 前，在**后端**安全配置 `AI_ENABLED=true` 和 `AI_API_KEY`，不要把密钥写入前端、代码库或聊天。服务使用 OpenAI-compatible `POST /chat/completions`、`deepseek-chat` 和 JSON 输出；仅发送当前任务记录的文本（最多 12000 字符），默认先对手机号/邮箱/身份证号脱敏。用户点击“采用建议”前，模型结果只作为建议返回，不会自动写入标注。启用后该文本会发送至 `AI_BASE_URL` 指定的服务；当前 DeepSeek URL 是托管的外部服务，请按组织的数据处理/留存政策配置。仅 HTTPS 可连接外部地址；HTTP 只允许本机回环服务。

数据响应默认启用敏感信息脱敏（手机号、邮箱、身份证号），可通过 `MASK_SENSITIVE_DATA=false` 关闭。仅 CSV、JSON 和 JSONL/NDJSON 文件可导入，每文件最多 10 MB、5000 条；单个任务最多分配 10000 条记录。导入的 Elastic 文档会写入 `dataset_id`，旧数据归入默认数据集。任务创建时会将数据 ID 快照写入 `task_items`，后续标注仅允许处理被分配到当前任务的记录。

`init-db` 会创建默认组织、默认项目、“情感分类”标签体系及默认数据集。组织 → 项目 → 数据集 → 任务构成项目层级；旧数据集迁移到默认项目。标签体系支持 2 至 100 个唯一编码/名称和颜色配置；每次更新都会写入版本历史。账号角色包括“超级管理员、项目管理员、任务负责人、标注员、审核员、数据分析员”；用户管理和审核/统计/导出等敏感接口由后端校验角色。自动任务分配会选择当前活动任务量较低的标注员。统计从 Elastic 聚合实时计算，并从 MySQL 汇总截止时间已过且未完成/未暂停的任务作为逾期 SLA 指标；成本指标尚未启用，等待项目计费规则。审核结果、标注历史和多模态标注与文档一起保存在 Elastic，配置变更写入 MySQL 审计日志。

项目成员通过 `project_members` 关联表管理。超级管理员和项目管理员可跨项目访问并管理成员；其他角色必须先被加入项目，才可访问项目下的数据集、任务、标注、审核、统计、导入/导出等数据接口，组织列表也只显示其成员项目所属组织。任务负责人必须是对应项目成员；自动分配只会选择项目成员中的标注员。质量检查的重复内容查询限定在当前数据集。按照当前迁移选择，旧账号不会自动加入默认项目；升级后请用 `init-admin` 将指定的全局管理员设为超级管理员，再为其他用户配置最小角色并逐项目添加成员。此前版本已将旧用户角色默认迁移为“项目管理员”的账号仍具有全局权限，请在上线隔离策略前逐个检查并将非管理员账号降为合适角色。

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

- `GET /api/data-items?page=1&page_size=20&label_status=all`：分页获取数据展示列表（需要登录；每页最多 100 条，支持标注状态、`dataset_id`、`task_id`、编号/内容搜索和低置信度优先排序）
- `GET /api/data-items/<id>`：获取单条数据详情（需要登录）
- `PUT /api/data-items/<id>/label`：保存/清除标签及可选的多模态 `annotation`（需要登录；可带 `task_id`，标签历史与多模态修改历史分别记录）
- `POST /api/data-items/<id>/issues`：提交数据异常反馈
- `GET /api/data-items/<id>/quality-check`：执行基础质量规则和当前数据集内的重复内容检查
- `GET /api/reviews?status=pending|approved|returned`、`PUT /api/data-items/<id>/review`：审核已标注数据
- `GET /api/data-items/export?format=jsonl|csv`：导出筛选后的数据

标注请求示例：

```json
{"label": "正向"}
```

未关联任务的旧数据兼容“正向 / 负向 / 中性”标签；任务标注使用任务关联标签体系中的标签。列表筛选支持按标注状态或具体标注值过滤，并显示数据插入时间和打标时间。标注结果、操作人和打标时间会写入对应 Elastic 文档。Elastic 不可用或索引不存在时，API 会返回错误，前端列表、详情和保存失败处均提供重试操作。

多模态 `annotation` 使用 `{"items":[...]}` 结构；`kind` 支持 `bbox`、`polygon`、`keypoint`、`segment`。图像坐标是 0–100 的百分比，时间片段使用秒数 `start`/`end`；单条标注最多 1000 项、JSON 大小最多 100 KB。

### 数据集、任务与标签体系

- `GET/POST /api/organizations`、`GET/POST /api/projects`：管理组织和项目
- `GET /api/projects/<id>/members`、`POST /api/projects/<id>/members`、`DELETE /api/projects/<id>/members/<user_id>`：查看或管理项目成员（管理接口仅限全局管理员）
- `GET/POST /api/datasets`：列出或创建数据集
- `POST /api/datasets/<id>/import`：以 multipart 字段 `file` 导入 CSV、JSON、JSONL/NDJSON
- `GET/POST /api/tasks`：列出或创建任务（数据集、标签体系、负责人、优先级、截止时间和说明）
- `PATCH /api/tasks/<id>`、`POST /api/tasks/<id>/auto-assign`：更新任务状态/负责人或按当前工作量自动分配
- `POST /api/tasks/<id>/items/<item_id>/skip`：跳过已分配数据
- `GET/POST /api/label-schemas`、`PUT /api/label-schemas/<id>`：管理标签体系和版本
- `GET /api/label-schemas/<id>/versions`：查看标签变更历史
- `GET /api/users`、`PATCH /api/users/<id>/role`：查看账号并配置角色
- `GET /api/stats`、`GET /api/audit-logs`：读取统计（含逾期任务）和配置操作审计记录
- `POST /api/data-items/<id>/pre-annotate`：为分配给当前用户的任务数据请求 AI 标签建议（需配置并启用模型服务）

## 前端联调

前端位于同级目录 `../we_fronted`。初始化 Elastic 后启动本 Flask 服务时使用 5000 端口；Vite 会将 `/api` 请求代理到 `http://127.0.0.1:5000`。账号名由 `init-admin` 命令创建；如果使用登录页面上的手机号登录，请将手机号作为用户名创建。

## 测试

```bash
python -m unittest discover -s tests -v
```

接口测试通过模拟 MySQL 和 Elasticsearch 连接运行，不需要启动数据库服务。
