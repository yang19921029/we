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

## 前端联调

前端位于同级目录 `../we`。启动本 Flask 服务时使用 5000 端口；Vite 会将 `/api` 请求代理到 `http://127.0.0.1:5000`。账号名由 `init-admin` 命令创建；如果使用登录页面上的手机号登录，请将手机号作为用户名创建。

## 测试

```bash
python -m unittest discover -s tests -v
```

接口测试通过模拟数据库连接运行，不需要启动 MySQL 服务。
