```markdown
# 应用授权（用户级 MCP Connectors）产品需求文档

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 状态 | 已上线（v1.0 范围） |
| 模块 | 个人中心 → 应用授权 |
| 关联代码 | 后端 `app/connectors/`、前端 `features/connectors/`、Migration 006 |
| 关联 commit | `0d7d086`、`a2678a9`（部署修复） |
| 上线环境 | https://aitravel.aigoway.tech/profile/connectors |

---

## 1. 背景与目标

### 1.1 背景

AI Travel Agent 当前的 MCP（Model Context Protocol）接入方式是**进程级**的：服务器统一持有一份 token，所有用户共用同一个第三方账号下的数据。这与 ChatGPT Apps、Claude Connectors、Cursor Connectors 等成熟产品的"应用链接"形态有本质差距：

- 用户无法授权自己的工作账号
- 无法保证数据隔离
- 无法满足"我连了 Notion，助手就能看我的页面"这类核心心智

### 1.2 目标

让用户在个人中心**人手一套**自己 OAuth 授权过的 MCP 连接，使 AI 助手能以用户本人身份代为访问其第三方应用数据。

具体到本期上线范围：

1. 用户能在"个人中心 → 应用授权"页面看到可授权的应用列表
2. 用户能完整走完 OAuth 2.1 授权流（含动态客户端注册、PKCE、resource indicator）
3. 授权完成后，所有聊天会话都能自动调用该应用的 MCP 工具，无需用户在每个会话单独勾选
4. 用户能随时查看授权状态、断开授权、重新授权

### 1.3 非目标

以下内容**不在本期范围**：

- 管理员后台 CRUD 维护 connector 列表（v1.0 通过 `connectors.json` 配置文件维护）
- 在单个会话内手动开关 connector（v1.0 默认全部已授权 connector 都参与每次聊天）
- 多账号共存（同一用户对同一 connector 同一时刻只保留一份授权）
- Client ID Metadata Documents（SEP-991，2025-11-25 引入）的简化注册路径
- 非 OAuth 鉴权方式（API Key、PAT 等）

---

## 2. 用户故事

### 2.1 主用户故事

> 作为一名已登录的旅行助手用户，我希望连接我的 Notion 工作区，让助手在帮我规划行程时能查阅我自己整理的旅行笔记。

### 2.2 衍生用户故事

- 作为用户，我希望看到清晰的"已连接 / 未连接"状态，知道当前哪些应用已授权
- 作为用户，我希望授权失败时能看到原因，并方便重新发起
- 作为用户，我希望随时可以断开某个应用的授权
- 作为用户，我希望授权过期或被撤销后系统能自动尝试刷新，刷新失败时给出明确提示

---

## 3. 设计原则

借鉴 ChatGPT / Claude Connectors 的成熟形态，遵循 MCP 官方授权规范（spec 版本 2025-06-18）：

| 规范 | 用途 |
|---|---|
| OAuth 2.1 | 授权框架基线 |
| RFC 9728 | Protected Resource Metadata，发现 MCP 服务器对应的授权服务器 |
| RFC 8414 | Authorization Server Metadata，发现授权端点 / token 端点 / 注册端点 |
| RFC 7591 | Dynamic Client Registration，免去手动申请 client_id |
| RFC 7636 | PKCE，防授权码截获 |
| RFC 8707 | Resource Indicators，强制 token 绑定到指定 MCP server |

核心设计原则：

1. **每个用户一份 token**：数据隔离
2. **加密落库**：access_token / refresh_token / client_secret 全部 AES-256-GCM 加密
3. **每轮聊天动态拼工具**：用户的 connector 工具不进全局 agent，而是在每次聊天开始时按 `user_id` 临时构建 MCP 客户端
4. **一行 SQL 查不到明文**：哪怕 DB 泄露，攻击者拿到的也是密文
5. **可复用现有 OAuth 基础设施**：不依赖第三方 SaaS（如 WorkOS），全部自实现，便于后续轮转密钥与适配新规范

---

## 4. 信息架构与导航

### 4.1 入口

`个人中心` 页面 `权限管理` 行下方，新增 `应用授权` 行，使用 `Plug` 图标，点击进入 `/profile/connectors`。

### 4.2 应用授权列表页

页面顶部：

- 标题："应用授权"
- 副标题："连接你的常用应用后，我可以代你查询、追踪进度。所有授权随时可以断开。"

页面主体：垂直列表，每条 connector 一张卡片，包含：

- 应用图标（来自 `icon_url`，缺失时回落到默认 `Plug` 图标）
- 应用名称
- 状态徽章（右上）
- 应用描述
- 错误信息（仅在非 connected 且有 last_error 时显示）
- 操作按钮（右下）

### 4.3 状态徽章对照

| 状态 | 显示文案 | 颜色 | 图标 |
|---|---|---|---|
| `connected` | 已连接 | emerald | CheckCircle2 |
| `pending` | 授权中 | amber | Loader2（旋转） |
| `expired` | 已过期 | orange | TriangleAlert |
| `revoked` | 已断开 | slate | — |
| `failed` | 授权失败 | rose | TriangleAlert |
| `disconnected` | 未连接 | slate | — |

### 4.4 操作按钮

| 当前状态 | 主按钮 | 副按钮 |
|---|---|---|
| `connected` | 重新授权 | 断开（红色，弹确认对话框） |
| 其他 | 连接 | — |

### 4.5 OAuth 跳转回流

授权完成后，浏览器被重定向回 `/profile/connectors?connector_id=xxx&connector_status=connected`。前端读取 query 参数：

- `connected` → toast 成功提示，刷新列表
- 其他 → toast 失败提示并展示 `connector_error`
- 处理完 query 参数后立即清理 URL，避免再次刷新页面重复弹 toast

---

## 5. 功能需求

### 5.1 列表与状态

| 编号 | 需求 |
|---|---|
| F1 | 用户进入页面后必须已登录（`/profile/connectors` 在 `RequireAuthRoute` 下） |
| F2 | 列表只展示 `enabled = true` 的 connector |
| F3 | 列表按 connector id 字母序稳定排序 |
| F4 | 同一用户对同一 connector 始终只展示一行最新状态 |
| F5 | 加载中显示 spinner，加载失败 toast 报错 |

### 5.2 发起授权

| 编号 | 需求 |
|---|---|
| F6 | 用户点击"连接"或"重新授权"，前端调用 `POST /api/connectors/{id}/authorize` |
| F7 | 后端按需完成 RFC 9728 / 8414 / 7591 三步发现与注册，生成 PKCE + state，落库后返回 `authorize_url` |
| F8 | 前端通过 `window.location.href` 跳转到 `authorize_url`，不在 iframe 内打开 |
| F9 | 同一 connector 已存在记录时，复用 client_id 与 client_secret，不重复注册 |
| F10 | OAuth state 必须绑定 user_id，回调时校验匹配，否则拒绝并清理 |
| F11 | OAuth state 有效期 600 秒，过期自动清理 |

### 5.3 完成授权

| 编号 | 需求 |
|---|---|
| F12 | OAuth 回调命中 `GET /api/connectors/oauth/callback`，凭 state 拿回 code_verifier 与 user_id |
| F13 | 用 code + code_verifier + resource 调用授权服务器 token 端点换取 token |
| F14 | access_token / refresh_token 经 AES-256-GCM 加密后写入 `user_mcp_authorizations` |
| F15 | 状态置为 `connected`，清空 `last_error` |
| F16 | 完成后 302 重定向回前端 `CONNECTOR_FRONTEND_RETURN_URL` 并附带 `connector_id` 和 `connector_status` |
| F17 | 任何环节失败：写入 `last_error`，状态置为 `failed`，回调仍重定向回前端并展示错误 |

### 5.4 断开授权

| 编号 | 需求 |
|---|---|
| F18 | 用户点击"断开"，弹出确认对话框 |
| F19 | 确认后调用 `DELETE /api/connectors/{id}` |
| F20 | 后端清空 access_token / refresh_token / expires_at，状态置为 `revoked` |
| F21 | 不删除整行记录，保留 client_id 以便用户后续重新授权时复用 |

### 5.5 自动 token 刷新

| 编号 | 需求 |
|---|---|
| F22 | 每次聊天开始时，对该用户所有 `connected` connector 检查 `expires_at` |
| F23 | 距过期不足 30 秒的 access_token 触发 `refresh_token_grant` |
| F24 | 刷新成功：用新 token 继续本次聊天 |
| F25 | 刷新失败：标记 `failed`，本次聊天跳过该 connector，不阻断聊天 |

### 5.6 聊天集成

| 编号 | 需求 |
|---|---|
| F26 | 全局 agent（系统 MCP + 本地工具）在应用启动时构建一次 |
| F27 | 每轮聊天进入前，按 `user_id` 实时构建 MCP client，加载该用户已授权 connector 的工具 |
| F28 | 用 `[*global_tools, *user_tools]` 重新调用 `create_agent` 生成本轮专属 agent |
| F29 | 聊天结束后，本轮临时 MCP client 自动关闭，避免连接泄露 |
| F30 | 单个 connector 加载工具失败时，错误降级，不阻塞其他 connector 与全局工具 |

---

## 6. 技术实现要点

### 6.1 数据模型

新增两张表（migration 006）：

**`user_mcp_authorizations`**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT | UUID 主键 |
| user_id | TEXT | FK → users.id |
| connector_id | TEXT | connector slug，例如 `notion` |
| mcp_server_url | TEXT | 冗余，避免 connector 配置变更影响历史授权 |
| authorization_server | TEXT | RFC 9728 发现得到 |
| client_id | TEXT | 动态注册结果 |
| client_secret_enc | TEXT | 加密后的 client_secret |
| redirect_uri | TEXT | 回调地址（固定） |
| access_token_enc | TEXT | 加密后的 access_token |
| refresh_token_enc | TEXT | 加密后的 refresh_token |
| token_type | TEXT | bearer |
| scope | TEXT | 实际授权 scope |
| expires_at | TEXT | ISO 时间戳 |
| status | TEXT | pending / connected / expired / revoked / failed |
| last_error | TEXT | 最近一次失败原因（截断 500 字符） |
| created_at, updated_at | TEXT | ISO 时间戳 |

唯一约束：`(user_id, connector_id)`。

**`connector_oauth_states`**

| 字段 | 类型 | 说明 |
|---|---|---|
| state | TEXT | 主键，OAuth state 值 |
| user_id | TEXT | 绑定用户，防 CSRF |
| connector_id | TEXT | 哪个 connector |
| authorization_id | TEXT | FK → user_mcp_authorizations.id |
| code_verifier | TEXT | PKCE verifier |
| redirect_after | TEXT | 完成后回到的前端 URL |
| expires_at | TEXT | TTL = 600 秒 |
| created_at | TEXT | ISO 时间戳 |

state 一次性消费：被回调成功命中后立即删除。

### 6.2 加密

- 算法：AES-256-GCM
- 密钥派生：`SHA-256(MCP_TOKEN_ENC_KEY)`
- 缺省回落：`MCP_TOKEN_ENC_KEY` 未设置时使用 `JWT_SECRET`，生产环境强烈建议显式配置以便独立轮转
- 落库格式：`base64url(nonce || ciphertext)`，nonce 12 字节，每次写入随机生成

### 6.3 配置文件

**`backend/config/connectors.json`**（gitignored，按部署环境维护）

每条记录字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| display_name | 是 | 列表显示名 |
| description | 否 | 列表副标题 |
| icon_url | 否 | 应用图标 |
| mcp_server_url | 是 | MCP 服务器 URL（注意 SSE / streamable_http 后缀差异） |
| default_scopes | 否 | 显式指定 scope，留空时自动取 server 公开的 scopes_supported |
| client_name / client_uri / logo_uri | 否 | 动态注册时附带的元信息 |
| enabled | 否 | 默认 true |

仓库提供 `connectors.example.json` 作为模板，包含 Notion 与 Linear 的初始配置。

### 6.4 模块结构

```
backend/app/connectors/
  __init__.py
  crypto.py        AES-GCM 加解密
  registry.py      读取 connectors.json
  store.py         user_mcp_authorizations + connector_oauth_states 仓储
  oauth.py         RFC 9728/8414/7591/7636/8707 实现
  service.py       业务编排：start/complete/disconnect/list_active
  runtime.py       async with user_connector_tools(...) 上下文管理器

backend/app/api/connectors.py    4 个 HTTP 端点
backend/app/schemas/connectors.py  对外数据模型

frontend/src/features/connectors/
  api/connectors.api.ts          HTTP 封装
  ui/connectors-page.tsx         列表 + 状态 + 操作

frontend/src/pages/profile/connectors.tsx   路由入口
```

### 6.5 API 契约

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| GET | `/api/connectors` | 当前用户视角下的应用列表 | 必须 |
| POST | `/api/connectors/{id}/authorize` | 发起授权，返回 `authorize_url` | 必须 |
| DELETE | `/api/connectors/{id}` | 断开授权 | 必须 |
| GET | `/api/connectors/oauth/callback` | OAuth 回调，重定向回前端 | 不要求 Bearer，靠 state 校验身份 |

`StartAuthorizationResponse`

```
{ authorize_url: string, state: string, expires_in: number }
```

`ConnectorState`

```
{
  id, display_name, description, icon_url, mcp_server_url, enabled,
  status, connected_at, last_error
}
```

### 6.6 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `MCP_TOKEN_ENC_KEY` | 推荐 | 凭证加密密钥；缺失时回落 `JWT_SECRET` |
| `CONNECTOR_REDIRECT_URL` | 是 | OAuth 回调，必须与各 MCP server 实际注册值完全一致 |
| `CONNECTOR_FRONTEND_RETURN_URL` | 是 | 完成后跳回的前端地址 |
| `CONNECTOR_CLIENT_URI` | 否 | 动态注册时附带，用于授权页展示 |
| `CONNECTOR_CLIENT_LOGO_URI` | 否 | 动态注册时附带 |
| `CONNECTORS_CONFIG_PATH` | 否 | 覆盖 `connectors.json` 默认路径 |

### 6.7 容器部署

`docker-compose.aliyun.yml` 中 backend 服务的 `volumes` 必须挂目录而不是单文件，否则后续添加任何配置都需要改 compose：

```
volumes:
  - ./backend/data:/app/data
  - ./backend/config:/app/config:ro
```

---

## 7. 安全与合规

| 风险 | 缓解措施 |
|---|---|
| token 落库被撞库 / 备份泄露 | AES-256-GCM 加密，密钥独立配置 |
| 授权码截获 | 全程 PKCE S256 |
| token 跨 audience 重放 | RFC 8707 resource 参数贯穿 authorize 与 token 请求 |
| 回调被 CSRF | state 绑定 user_id，回调校验 user 一致；state 一次性消费 |
| state 被穷举 | `secrets.token_urlsafe(24)` ≈ 192 bit 熵 |
| token 过期但 refresh 失败导致用户无声中断 | 失败标记 `failed` 并写入 `last_error`，前端展示提示 |
| 单个 connector 故障拖垮聊天 | 每轮聊天对 connector 工具加载隔离 try/except，失败降级跳过 |
| connector 配置文件被打包进镜像 | `connectors.json` 在 `.gitignore`，仅在部署目录维护 |

---

## 8. 部署清单（v1.0 实操记录）

1. 后端依赖新增 `cryptography>=43.0.0,<50.0.0`
2. 数据库迁移：migration 006 自动应用（无需停机，新增表）
3. 服务器 `.env` 追加 5 个新变量（已通过部署脚本完成）
4. 服务器 `backend/config/connectors.json` 部署（gitignored，需要单独 scp 或在 1Panel 编辑）
5. `docker-compose.aliyun.yml` 卷挂载从单文件改为目录
6. 容器重建：`docker compose -f docker-compose.aliyun.yml up -d --build`
7. 前端构建并通过 `deploy/aliyun/sync_aitravel_frontend.ps1` 发布到 OpenResty
8. 1Panel 域名站点不需要改 conf；前端 SPA 路由 `/profile/connectors` 由 `try_files` 兜底，OAuth 回调 `/api/connectors/oauth/callback` 由现有 `/api/` 反代规则覆盖

---

## 9. 验收标准

| 编号 | 验收点 |
|---|---|
| A1 | 未登录访问 `/profile/connectors` 跳转登录页 |
| A2 | 已登录访问列表能看到所有 `enabled` connector |
| A3 | 点击 Notion "连接" 跳转到 `https://mcp.notion.com/...` 系列授权页 |
| A4 | 完成授权后回到列表，状态为"已连接"，弹出成功 toast |
| A5 | 拒绝授权或网络中断后状态为"授权失败"或"未连接"，显示错误并支持重试 |
| A6 | 已连接状态下进入聊天，发送涉及 Notion 的提问，agent 应能调到 Notion 工具 |
| A7 | 点"断开"并确认后状态变为"已断开"，再次进入聊天该 connector 工具不再加载 |
| A8 | access_token 临近过期时自动刷新，用户无感知 |
| A9 | DB 中 `access_token_enc` / `refresh_token_enc` 列为 base64 密文，不可直接还原 |
| A10 | 连续 5 次随机错误 state 命中回调，全部正常重定向到前端错误页，不报 5xx |

---

## 10. 测试覆盖

后端：

- `tests/test_connectors_crypto.py` — 加解密往返、密钥回落、密钥缺失报错
- `tests/test_connectors_oauth.py` — PKCE 配对、canonical URI 规范化、authorize_url 拼装、scope 合并
- `tests/test_db_migrate.py` 与 `tests/test_sqlite_store.py` — 已更新到 migration 006

前端：

- 复用 `Toast`、`ConfirmDialog`、`PageBackButton` 等既有 primitives，无需为它们新增测试
- 新页面通过类型检查（`tsc --noEmit`）
- 全部 54 个既有 vitest 用例无回归

---

## 11. 已知限制

1. 当前 connector 列表通过文件维护，需要发版才能新增；后续可演进为后台 CRUD
2. 不支持同一用户在同一 connector 下挂多个工作区（需要扩展唯一约束）
3. 不支持仅在指定会话启用某个 connector，授权后默认全局参与
4. 不支持 Client ID Metadata Documents（SEP-991），仍走 RFC 7591 动态注册路径
5. 部分 MCP 服务商可能要求非标准 token 端点鉴权方式（如 `private_key_jwt`），当前仅实现 `client_secret_basic`
6. 暴露给 agent 的工具名前缀来自 connector id；连接较多时上下文中工具数量会显著增长，目前未做前置筛选

---

## 12. 后续演进路线

- v1.1：在聊天会话内提供 connector 开关，支持本会话临时禁用某 connector
- v1.2：支持单 connector 多账号（例如同一用户连接两个 Notion 工作区）
- v1.3：管理员后台维护 connector 列表，支持热加载
- v1.4：接入 SEP-991（Client ID Metadata Documents），免去动态注册
- v1.5：在工具调用层引入 connector-aware 的工具召回，避免 30+ 工具同时进上下文
- v1.6：支持非 OAuth 的 connector 接入方式（API Key / PAT），覆盖部分企业内部 MCP

---

## 13. 关键决策记录

| 决策 | 取舍 | 结论 |
|---|---|---|
| 是否为 connector token 单独建库 | 与现有 `chat.db` 同库省去运维成本 vs. 单独库便于权限隔离 | 同库，加密落库已能覆盖大部分泄露面 |
| 每轮聊天临时构建 agent vs. 长连接 MCP client | 长连接性能更好但需要复杂的连接池与 token 续期上的并发控制 | 临时构建：实现简单、隔离性强；性能可后续观测后再优化 |
| token 加密密钥独立 vs. 复用 `JWT_SECRET` | 独立便于轮转 | 推荐独立（`MCP_TOKEN_ENC_KEY`），缺省回落 `JWT_SECRET` 兜底 |
| state 存 DB vs. 短 JWT | DB 增加表 vs. 无状态 | 选 DB：state 必须是一次性消费，DB 删除天然实现，且方便记录关联授权 |
| `connectors.json` 是否进 git | 是：版本可追溯 / 否：避免泄露公开应用元数据 | 否（与现有 `mcp.servers.json` 保持一致），仓库只放 `.example` |

---

## 14. 名词对照

| 中文 | 英文 / 协议术语 |
|---|---|
| 应用 | connector |
| 应用授权 | user-level MCP authorization |
| 资源服务器 | MCP server / OAuth resource server |
| 授权服务器 | authorization server |
| 动态注册 | Dynamic Client Registration (RFC 7591) |
| 资源指示器 | Resource Indicators (RFC 8707) |
| 临时校验码 | PKCE code_verifier / code_challenge (RFC 7636) |
```

需要的话直接复制粘贴成 `docs/connectors-prd.md` 即可。要我把它写进文件并 commit 吗？

下面这一节可以直接追加在 PRD 里（建议放在 `13. 关键决策记录` 之后、`14. 名词对照` 之前）。

---

## 14. 学习笔记：为什么不像 GitHub 那样手动注册应用

这是接入 MCP OAuth 时最容易困惑的一点。新工程师上来都会问：为什么 Notion / Linear 的 MCP 不需要我们去后台先建一个 "OAuth App"，填好回调地址、拿到 client_id 和 client_secret？这一节专门记录这背后的协议差异和取舍。

### 14.1 一句话答案

GitHub 走的是**传统 OAuth**：要求开发者预先在它的后台填表，生成长期的 `client_id / client_secret`。
Notion / Linear 的 MCP 端点走的是 **OAuth 2.1 + RFC 7591 Dynamic Client Registration（DCR）**：服务器允许客户端在第一次连接时**用代码自动调一个 `/register` 端点临时注册一个 client**，所以不需要人工在它们后台手动建应用。

这不是 Notion / Linear 比 GitHub 进步，而是它们专门为 MCP 客户端生态做的设计选择。

### 14.2 为什么 MCP 选 DCR 而不是 GitHub 那套

GitHub 的 OAuth 模型隐含三个假设：

- 接入方数量少且可控（"OAuth Apps" 是产品维度）
- 每个接入方都有运营人员能去填表
- `client_id` 是品牌资产，绑定的是"GitHub × 你公司这个产品"这条关系

但 MCP 的世界正好相反：

- MCP 客户端可能是任何 LLM 应用、IDE、Agent——Claude、Cursor、Zed、ChatGPT、自研 Agent，未来还会冒出无数个
- 这些客户端事先不知道用户会想连哪个 MCP server——用户今天连 Notion，明天连 Linear，后天连一个完全没人听过的内部 MCP
- 每加一个 MCP server 就要"先去对方后台手动注册一下应用，把 redirect_uri 填好"，体验完全不可接受

所以 [MCP 规范 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) 明确写道：

> Authorization servers and MCP clients **SHOULD** support the OAuth 2.0 Dynamic Client Registration Protocol (RFC 7591).

意思是：MCP server 应该允许客户端当场自己注册自己，不要求人工干预。

### 14.3 在我们这套实现里它发生在哪一步

入口是 `app/connectors/oauth.py` 里的 `register_client(...)`。该函数在用户第一次点"连接 Notion"时被调用，向 Notion 的授权服务器发出：

```
POST https://<notion-as>/register
{
  "client_name": "AI Travel Agent",
  "redirect_uris": ["https://aitravel.aigoway.tech/api/connectors/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "client_secret_basic"
}
```

Notion 的授权服务器收到后会**当场返回一个 client_id 和 client_secret**。我们把它加密写入 `user_mcp_authorizations.client_id` 与 `client_secret_enc`，后续这个用户对这个 connector 的所有 OAuth 请求都复用这对凭证。

整个链路一次都不需要打开 Notion 后台填表。

### 14.4 那 redirect_uri 怎么对得上

| | 传统 OAuth（GitHub） | DCR（MCP） |
|---|---|---|
| 谁先约定 redirect_uri | 开发者去后台预填 | 客户端在 `/register` 请求里携带 |
| 运行时校验逻辑 | 用 authorize 请求里的 redirect_uri 与后台预填值对比 | 用 authorize 请求里的 redirect_uri 与 `/register` 时存下来的对比 |

DCR 不是"取消了 redirect_uri 校验"，而是把"先注册再用"压成了"注册即首次使用"。我们一次性在 `.env` 里配 `CONNECTOR_REDIRECT_URL`，注册时传过去，之后所有请求都只能用这个值，对不上一样会被授权服务器拒绝。安全性等价。

### 14.5 为什么 GitHub 不支持这个

几个现实原因：

1. **GitHub OAuth 是 2010 年代初设计的**，那时 RFC 7591 还没出，整个生态约定就是"开发者后台手填"。GitHub 没有改的动力——存量集成全基于 `client_id` 这套。
2. **GitHub 的运营模型依赖 client_id**：API rate limit、滥用追踪、品牌展示页全是按 `client_id` 维度做的。开放 DCR 等于让任何人都能即时申请一个"无主"的 `client_id`，运营会失控。
3. **GitHub 不是为 LLM 接入设计的**。它的核心场景仍然是"开发者把自己的产品集成 GitHub 登录"，量不大、节奏慢、可以人工。

值得注意：Notion / Linear 也**有**传统的 OAuth Apps 后台（例如 https://www.notion.so/my-integrations 仍然能手动建集成），只是它们的 MCP 端点专门为 MCP 客户端这条链路开了 DCR 入口，是另一条流程。

### 14.6 这套设计的代价

DCR 不是免费的，它把几个责任挪到了客户端：

- **每个用户对每个 connector 都会注册一份 client_id / client_secret**：所以 `user_mcp_authorizations` 表里每行都有自己的凭证，不像 GitHub 那样全公司共用一个长期 client。这正是这张表里要存 `client_id` 和 `client_secret_enc` 的原因。
- **server 端没有人审核我们的"应用"**：没有图标审核、没有发布上架。授权页上展示的 "AI Travel Agent" 完全来自注册时填的 `client_name`，所以**钓鱼风险更高**——server 那边需要在授权页上明确告诉用户"你授权的是一个动态注册的客户端"，用户也要警惕。
- **client_secret 生命周期更短**：spec 建议短生命周期，server 可以随时回收。我们当前实现已经支持 refresh_token 自动续 access_token，但如果 server 决定整个回收 client_secret，需要走"重新授权"路径——前端的"重新授权"按钮就是为这个准备的。

### 14.7 后续演进：SEP-991 / Client ID Metadata Documents

DCR 的代价之一是"任何客户端都能注册"。为了解决这个问题，[2025-11-25 MCP spec](https://modelcontextprotocol.io/specification/latest/basic/authorization) 引入了 **SEP-991 Client ID Metadata Documents（CIMD）**：

- 客户端不再每次现场注册
- 而是在自己的域名下发布一个公网 metadata 文档，里面声明 `client_name`、`redirect_uris`、`logo_uri` 等
- 授权服务器把这个 URL 当作"长期 client_id"
- 每次授权时去拉一次该 URL 验证客户端身份

效果上：DCR 的免人工注册 + GitHub 的"客户端有稳定身份"，两边的优点都拿到。代价是 MCP server 那边要支持 CIMD，目前生态尚未普及，所以**当前我们仍然走 DCR 是稳的**，CIMD 列在 PRD §12 v1.4 演进路线里。

### 14.8 调试时如何验证 DCR 真的发生了

实操时如果想看 DCR 调用确实生效，可以：

1. 后端打开 DEBUG 日志，看 `httpx` 对 `/register` 端点的请求和返回
2. 或者第一次连接成功后，去查 `user_mcp_authorizations` 表：

```sql
SELECT connector_id, client_id, length(client_secret_enc) AS secret_len, status
FROM user_mcp_authorizations
WHERE user_id = '<某用户>';
```

如果 `client_id` 不为空、`secret_len` 大于 0，就说明 DCR 已经成功完成。

### 14.9 一句话总结

> GitHub 的 OAuth 是为"少数稳定的接入方"设计的，所以要人工注册。
> MCP 的 OAuth 是为"任意未知的 LLM 客户端"设计的，所以走 RFC 7591 让客户端自己注册。
> 我们这套实现完整跟进了这个设计——所以看不到"去 Notion 后台建应用"那一步，它就是不存在。