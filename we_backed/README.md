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

升级代码后请重新运行 `flask --app app init-db`。该命令会幂等创建组织、项目、数据集、数据集版本、导出历史、AI 预标注评估、双人标注提交与仲裁记录、标签体系、任务、任务数据、审计日志等表，并为旧数据集补上默认项目归属、补齐默认菜单和旧用户表中的角色/启用状态字段；已有用户保留原账号，角色默认为“项目管理员”，账号默认为启用状态。

人员与权限页面支持创建账号、修改登录账号和角色、重置密码以及启用/禁用账号。禁用采用软禁用，不删除项目成员和历史记录；被禁用账号不能登录，已有会话在下次 API 请求时失效。禁用或降级管理员前，系统会保留至少一名启用的管理员。

数据记录存放在 Elasticsearch，不再从 MySQL 的旧 `data_items` 表读取。设置 Elastic 连接后，运行 `flask --app app init-elastic` 可创建索引并写入示例数据；若索引已经存在，该命令只更新分页窗口和兼容字段映射，不会覆盖或补写其中的数据。

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
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SENDER=
SMTP_USE_SSL=false
SMTP_STARTTLS=true
SMTP_TIMEOUT=10
```

使用认证时必须同时设置用户名和密码。业务索引文档以 Elastic `_id` 作为数据编号，正文使用 `content` 或 `text` 字段。插入时间优先读取 `inserted_at`、`created_at`、`@timestamp` 或 `timestamp`，兼容历史数据时回退显示 `order_date`；打标时间读取 `labeled_at`，历史数据兼容回退 `updated_at`。新的打标操作会同时写入 `labeled_at` 和 `updated_at`。

邮箱找回密码需要在后端配置 SMTP_HOST、SMTP_SENDER 和邮件服务凭据；支持 STARTTLS（默认）或 `SMTP_USE_SSL=true` 的 SSL 连接。用户登录后从顶部“账号安全”验证并绑定邮箱，只有已验证邮箱可用于找回；验证码有效 10 分钟，单次使用且每账号每项操作至少间隔 60 秒。未绑定邮箱的旧账号请由管理员通过“人员与权限”重置密码。SMTP 未配置时，验证码发送接口会明确返回服务不可用，不会更改邮箱或密码。

顶部在线人数按最近 5 分钟内有心跳的启用账号去重统计；前端每分钟发送一次心跳，正常退出会立即移除当前会话，关闭浏览器或设备断网的会话会在 5 分钟后过期。

AI 预标注默认关闭。启用 DeepSeek 前，在**后端**安全配置 `AI_ENABLED=true` 和 `AI_API_KEY`，不要把密钥写入前端、代码库或聊天。服务使用 OpenAI-compatible `POST /chat/completions`、`deepseek-chat` 和 JSON 输出；仅发送当前任务记录的文本（最多 12000 字符），默认先对手机号/邮箱/身份证号脱敏。用户点击“采用建议”前，模型结果只作为建议返回，不会自动写入标注。启用后该文本会发送至 `AI_BASE_URL` 指定的服务；当前 DeepSeek URL 是托管的外部服务，请按组织的数据处理/留存政策配置。仅 HTTPS 可连接外部地址；HTTP 只允许本机回环服务。

数据响应默认启用敏感信息脱敏（手机号、邮箱、身份证号），可通过 `MASK_SENSITIVE_DATA=false` 关闭。仅 CSV、JSON 和 JSONL/NDJSON 文件可导入，每文件最多 1 GB（1024 MB），记录条数不限；单条记录最多 50 MB。导入接口支持 multipart 字段 `preview_only=true` 执行全文件预检并返回字段、记录总数和最多 10 条样例，不写入数据；确认后重新上传并导入。正式导入先进行流式校验，再按最多 100 条或约 5 MB 分批写入 Elasticsearch，所有批次完成后统一刷新索引；单条超大记录会单独成批。后端临时磁盘及反向代理必须允许并容纳 1 GB 上传请求；若部署在 Nginx 等代理之后，应相应提高请求体上限和超时。单个任务最多分配 10000 条记录。导出使用 Elasticsearch 滚动分页，不限制匹配记录总数；下载完成或失败后会更新个人导出历史，客户端中断的下载会记为失败。导入有成功写入时会生成数据集版本；任务同时保留创建时的版本关联和数据 ID 快照，后续标注仅允许处理被分配到当前任务的记录。任务可选第二位标注员：双方必须独立提交同一数据集标签体系内的标签；结果一致时进入常规审核，不一致时进入仲裁队列。双人标注暂不支持跳过数据或提交多模态标注。

`init-db` 会创建默认组织、默认项目、“情感分类”标签体系及默认数据集。组织 → 项目 → 数据集 → 任务构成项目层级；旧数据集迁移到默认项目。标签体系支持 2 至 100 个唯一编码/名称和颜色配置；每次更新都会写入版本历史。账号角色包括“超级管理员、项目管理员、任务负责人、标注员、审核员、数据分析员”；后端按角色返回菜单，首页快捷入口也只显示该角色可访问的菜单项；用户管理和审核/统计/导出等敏感接口仍由后端校验角色。自动任务分配按项目统计未完成任务数据量，优先选择当前待处理工作量较低的标注员；管理员可跨任务批量改派，但每个任务仍须分别通过项目成员校验。异常反馈状态、处理说明、通知和质检规则保存在 MySQL；通知按收件人隔离。审核趋势按月统计通过/退回数量；AI 预标注在人工保存标签后记录建议采纳结果，评估汇总按当前账号可访问项目范围统计。统计从 Elastic 聚合实时计算，并从 MySQL 汇总截止时间已过且未完成/未暂停的任务作为逾期 SLA 指标；成本指标尚未启用，等待项目计费规则。审核结果、标注历史和多模态标注与文档一起保存在 Elastic，配置变更写入 MySQL 审计日志。

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
- `POST /api/auth/change-password`：校验当前密码后修改密码（需要登录）
- `POST /api/auth/presence`：更新当前会话心跳并返回在线账号数（需要登录）
- `GET /api/auth/recovery-email`、`POST /api/auth/recovery-email/send-code`、`POST /api/auth/recovery-email/verify`：查看、发送验证码并绑定已验证的恢复邮箱（需要登录）
- `POST /api/auth/forgot-password/send-code`、`POST /api/auth/forgot-password/reset`：向已验证邮箱发送验证码并重置密码（无需登录）

### 获取一级菜单

`GET /api/menus`（需要登录）

### 获取指定一级菜单下的二级菜单

`GET /api/menus/<menu_id>/children`（需要登录）

例如 `GET /api/menus/2/children`。一级及二级菜单目前从初始化示例数据读取，可按项目需要调整数据库数据。

### 数据展示与标注

- `GET /api/data-items?page=1&page_size=20&label_status=all`：分页获取数据展示列表（需要登录；每页最多 100 条，支持标注状态、`dataset_id`、`task_id`、编号/内容搜索和低置信度优先排序）。响应中的 `pit_id` 和 `next_cursor` 可作为下一页请求的 `pit_id` 和 `after` 参数；PIT 快照每次翻页续期 5 分钟，支持稳定的前后翻页。未提供 PIT 参数的旧式页码请求仍兼容 `from` 分页。
- `GET /api/data-items/<id>`：获取单条数据详情（需要登录）
- `PUT /api/data-items/<id>/label`：保存/清除标签及可选的多模态 `annotation`（需要登录；可带 `task_id`，标签历史与多模态修改历史分别记录）
- `POST /api/data-items/<id>/issues`：提交数据异常反馈
- `GET /api/issues?page=1&page_size=20&status=待处理`、`PATCH /api/issues/<id>`：按权限列出并更新异常状态、处理人和处理说明；“已解决”必须提供处理说明
- `GET /api/notifications?page=1&page_size=20`、`PATCH /api/notifications/<id>/read`：读取当前用户通知并标记已读
- `GET /api/quality-rules`、`PUT /api/quality-rules`：查询/配置自动质检规则；仅管理员可保存，最小内容长度范围为 1 至 1000
- `GET /api/data-items/<id>/quality-check`：执行基础质量规则和当前数据集内的重复内容检查
- `GET /api/reviews?status=pending|approved|returned`、`PUT /api/data-items/<id>/review`：审核已标注数据
- 审核列表支持 `page`、`page_size`、`dataset_id`、`annotator`、`date_from`、`date_to` 筛选；默认每页 20 条，最多 100 条
- `GET /api/data-items/export?format=jsonl|csv`：通过 Elasticsearch 滚动分页导出筛选后的全部数据
- `GET /api/exports/history?page=1&page_size=20`：查询当前用户自己的导出状态和记录数
- `GET /api/quality-trends?dataset_id=<id>`：按月读取当前可访问范围内的审核通过/退回趋势；`dataset_id` 可选
- `GET /api/arbitrations?page=1&page_size=20`：查询当前可访问项目内待仲裁的双人标注分歧（最多每页 100 条）
- `POST /api/tasks/<id>/items/<item_id>/arbitrate`：由审核员选择最终标签并提交必填仲裁说明

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
- `POST /api/datasets/<id>/import`：以 multipart 字段 `file` 导入 CSV、JSON、JSONL/NDJSON；可先传 `preview_only=true` 预检
- `GET /api/datasets/<id>/versions`：查看当前有权访问数据集的导入版本
- `GET/POST /api/tasks`：列出或创建任务（数据集、标签体系、负责人、优先级、截止时间和说明）。带 `page`、`page_size` 时返回分页对象；分页默认每页 20 条、最多 100 条。任务分页仅聚合当前页任务的数据量和已标注量；不带分页参数的请求仍返回完整任务数组，供标注任务选择器使用。
- `PATCH /api/tasks/<id>`、`POST /api/tasks/<id>/auto-assign`：更新任务状态/负责人或按当前工作量自动分配；创建任务进入待标注，标注完成进入待审核，审核退回会回到标注流程，全部审核通过后自动完成，待审核和已完成状态不可手动设置
- `POST /api/tasks/batch-assign`：将 1 至 100 个任务分配给同一项目成员；每个任务都必须属于当前账号可访问的项目，且负责人必须是所有所选项目的有效成员
- `POST /api/tasks/<id>/items/<item_id>/skip`：跳过已分配数据
- `GET/POST /api/label-schemas`、`PUT /api/label-schemas/<id>`：管理标签体系和版本
- `GET /api/label-schemas/<id>/versions`：查看标签变更历史
- `GET /api/users`、`PATCH /api/users/<id>/role`：查看账号并配置角色
- `GET /api/stats`、`GET /api/audit-logs`：读取统计（含逾期任务）和配置操作审计记录
- `POST /api/data-items/<id>/pre-annotate`：为分配给当前用户的任务数据请求 AI 标签建议（需配置并启用模型服务）
- `GET /api/ai-evaluation`：按当前用户可访问项目统计已人工评估的 AI 建议采纳率及模型明细

## 前端联调

前端位于同级目录 `../we_fronted`。初始化 Elastic 后启动本 Flask 服务时使用 5000 端口；Vite 会将 `/api` 请求代理到 `http://127.0.0.1:5000`。账号名由 `init-admin` 命令创建；如果使用登录页面上的手机号登录，请将手机号作为用户名创建。

## 测试

```bash
python -m unittest discover -s tests -v
```

接口测试通过模拟 MySQL 和 Elasticsearch 连接运行，不需要启动数据库服务。
