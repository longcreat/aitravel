# MCP OAuth 2.1 授权流程：端点与资源文档

基于 Notion MCP 和 Linear MCP 的真实响应整理。

---

## 一、协议层次概览

```
MCP Client（我们的后端）
  │
  ├── 1. 问 MCP Server：你的授权服务器在哪？        RFC 9728
  ├── 2. 问授权服务器：你的各端点在哪？              RFC 8414
  ├── 3. 向注册端点注册自己，拿 client_id           RFC 7591
  ├── 4. 把用户浏览器重定向到授权端点               OAuth 2.1 + PKCE
  ├── 5. 用户同意后，用 code 换 token              RFC 7636
  └── 6. 携带 access_token 调用 MCP Server        RFC 8707
```

---

## 二、第一步：发现 MCP Server 的授权服务器

**规范：RFC 9728 Protected Resource Metadata**

客户端不知道 MCP server 用哪个授权服务器，先问它。

### 请求

```
GET /.well-known/oauth-protected-resource/{mcp_path}
Host: {mcp_server_host}
```

Notion 实际请求：
```
GET https://mcp.notion.com/.well-known/oauth-protected-resource/mcp
```

Linear 实际请求：
```
GET https://mcp.linear.app/.well-known/oauth-protected-resource
```

### 响应格式（标准字段）

| 字段 | 类型 | 含义 |
|---|---|---|
| `resource` | string | 该 MCP server 的 canonical URI，后续 token 请求的 `resource` 参数要用这个值（RFC 8707） |
| `authorization_servers` | array | 授权服务器列表，客户端取第一个 |
| `bearer_methods_supported` | array | token 传递方式，通常是 `["header"]` |
| `resource_name` | string | 可选，展示用名称 |
| `scopes_supported` | array | 可选，支持的 scope 列表 |

### Notion 实际响应

```json
{
  "resource": "https://mcp.notion.com/mcp",
  "authorization_servers": ["https://mcp.notion.com"],
  "bearer_methods_supported": ["header"],
  "resource_name": "Notion MCP (Beta)"
}
```

### Linear 实际响应

```json
{
  "resource": "https://mcp.linear.app",
  "authorization_servers": ["https://mcp.linear.app"],
  "bearer_methods_supported": ["header"]
}
```

**关键信息：** 从 `authorization_servers[0]` 拿到授权服务器的 issuer，带到第二步。

---

## 三、第二步：发现授权服务器的所有端点

**规范：RFC 8414 Authorization Server Metadata**

拿到 issuer 后，去它的 `.well-known/oauth-authorization-server` 问端点细节。

### 请求

```
GET /.well-known/oauth-authorization-server
Host: {issuer_host}
```

Notion 实际请求：
```
GET https://mcp.notion.com/.well-known/oauth-authorization-server
```

Linear 实际请求：
```
GET https://mcp.linear.app/.well-known/oauth-authorization-server
```

### 响应格式（标准字段）

| 字段 | 类型 | 含义 |
|---|---|---|
| `issuer` | string | 授权服务器 canonical URL |
| `authorization_endpoint` | string | 用户授权跳转的地址（第四步） |
| `token_endpoint` | string | 用 code 换 token 的地址（第五步） |
| `registration_endpoint` | string | 动态注册端点（第三步），可选 |
| `revocation_endpoint` | string | 撤销 token 的地址 |
| `response_types_supported` | array | 支持的 response_type，MCP 只用 `code` |
| `grant_types_supported` | array | 支持的授权类型 |
| `token_endpoint_auth_methods_supported` | array | token 端点的客户端鉴权方式 |
| `code_challenge_methods_supported` | array | 支持的 PKCE 方式，应包含 `S256` |
| `client_id_metadata_document_supported` | bool | 是否支持 SEP-991 CIMD（新规范，2025-11-25） |

### Notion 实际响应

```json
{
  "issuer": "https://mcp.notion.com",
  "authorization_endpoint": "https://mcp.notion.com/authorize",
  "token_endpoint": "https://mcp.notion.com/token",
  "registration_endpoint": "https://mcp.notion.com/register",
  "revocation_endpoint": "https://mcp.notion.com/token",
  "response_types_supported": ["code"],
  "response_modes_supported": ["query"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post",
    "none"
  ],
  "code_challenge_methods_supported": ["plain", "S256"],
  "client_id_metadata_document_supported": false
}
```

### Linear 实际响应

```json
{
  "issuer": "https://mcp.linear.app",
  "authorization_endpoint": "https://mcp.linear.app/authorize",
  "token_endpoint": "https://mcp.linear.app/token",
  "registration_endpoint": "https://mcp.linear.app/register",
  "revocation_endpoint": "https://mcp.linear.app/token",
  "response_types_supported": ["code"],
  "response_modes_supported": ["query"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post",
    "none"
  ],
  "code_challenge_methods_supported": ["S256"],
  "client_id_metadata_document_supported": true
}
```

**关键差异：**
- Notion 的 PKCE 支持 `plain` 和 `S256`，我们只用 `S256`（安全）
- Linear 的 `client_id_metadata_document_supported: true`，意味着它支持 SEP-991 新规范（Notion 是 false）
- 两家的 `revocation_endpoint` 都指向 `token_endpoint`，说明撤销用同一个端点

---

## 四、第三步：动态注册 client

**规范：RFC 7591 Dynamic Client Registration**

只在该用户对该 connector 没有 `client_id` 时执行一次。

### 请求

```
POST {registration_endpoint}
Content-Type: application/json

{
  "client_name": "AI Travel Agent",
  "redirect_uris": ["https://aitravel.aigoway.tech/api/connectors/oauth/callback"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "client_secret_basic",
  "client_uri": "https://aitravel.aigoway.tech",
  "logo_uri": "https://aitravel.aigoway.tech/icon-512.png"
}
```

### 响应（关键字段）

| 字段 | 含义 |
|---|---|
| `client_id` | 授权服务器分配的客户端 ID |
| `client_secret` | 对应密钥，加密后存库 |
| `token_endpoint_auth_method` | 最终确认的鉴权方式 |
| `redirect_uris` | 服务器接受的回调地址（原样回显我们填的值） |

这一步完成后，我们把 `client_id` 和加密后的 `client_secret` 写入 `user_mcp_authorizations` 表。下次同一用户对同一 connector 发起授权，复用这对凭证，不再重复注册。

---

## 五、第四步：把用户重定向到授权页

### 请求（浏览器跳转）

```
GET {authorization_endpoint}
  ?response_type=code
  &client_id={client_id}
  &redirect_uri={redirect_uri}
  &state={random_state}
  &code_challenge={pkce_challenge}
  &code_challenge_method=S256
  &resource={mcp_server_canonical_uri}   ← RFC 8707，把 token 绑定到这个资源
  &scope={requested_scope}
```

Notion 示例：
```
GET https://mcp.notion.com/authorize
  ?response_type=code
  &client_id=xxx
  &redirect_uri=https%3A%2F%2Fairtravel.aigoway.tech%2Fapi%2Fconnectors%2Foauth%2Fcallback
  &state=abc123
  &code_challenge=yyy
  &code_challenge_method=S256
  &resource=https%3A%2F%2Fmcp.notion.com%2Fmcp
```

**PKCE 参数生成方式：**

```
code_verifier  = base64url( random_bytes(32) )
code_challenge = base64url( sha256( code_verifier ) )
```

verifier 只在本地留存（我们存在 `connector_oauth_states.code_verifier`），challenge 发出去。

**state 作用：** 防 CSRF。我们把 `state` 与 `user_id`、`connector_id`、`code_verifier` 一起存库，回调时验证对得上才继续。

---

## 六、第五步：OAuth 回调，用 code 换 token

用户在授权页同意后，浏览器被重定向到我们的回调地址：

```
GET https://aitravel.aigoway.tech/api/connectors/oauth/callback
  ?code={authorization_code}
  &state={state_we_sent}
```

### 我们的后端用 code 换 token

```
POST {token_endpoint}
Authorization: Basic base64(client_id:client_secret)   ← client_secret_basic 鉴权
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code={code}
&redirect_uri={redirect_uri}
&client_id={client_id}
&code_verifier={verifier_from_state_table}    ← PKCE 验证
&resource={mcp_server_canonical_uri}          ← RFC 8707
```

### 响应

| 字段 | 含义 |
|---|---|
| `access_token` | 调用 MCP server 用的令牌，加密存库 |
| `refresh_token` | 用于自动续期，加密存库 |
| `token_type` | 固定 `bearer` |
| `expires_in` | 秒数，换算成 `expires_at` 时间戳存库 |
| `scope` | 实际授权的 scope |

---

## 七、第六步：带 token 调用 MCP Server

```
POST https://mcp.notion.com/mcp
Authorization: Bearer {access_token}
Content-Type: application/json

{ ... MCP 协议请求体 ... }
```

如果 access_token 过期，服务器返回 `401 Unauthorized`，客户端应使用 refresh_token 重新获取。

### 用 refresh_token 续期

```
POST {token_endpoint}
Authorization: Basic base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token
&refresh_token={stored_refresh_token}
&client_id={client_id}
&resource={mcp_server_canonical_uri}
```

---

## 八、如果你要自己实现一套兼容的 MCP OAuth Server

需要暴露以下端点：

| 端点 | 路径（推荐） | 规范 | 必须/可选 |
|---|---|---|---|
| Protected Resource Metadata | `/.well-known/oauth-protected-resource` | RFC 9728 | **必须** |
| Authorization Server Metadata | `/.well-known/oauth-authorization-server` | RFC 8414 | **必须** |
| 授权端点 | `/authorize` | OAuth 2.1 | **必须** |
| Token 端点 | `/token` | OAuth 2.1 | **必须** |
| 动态注册端点 | `/register` | RFC 7591 | **强烈建议** |
| 撤销端点 | `/token`（复用）或 `/revoke` | RFC 7009 | 建议 |

每个端点需要做的事：

**`/.well-known/oauth-protected-resource`**
- 返回 JSON，声明 `resource`（canonical URI）和 `authorization_servers`
- MCP client 凭这里找到授权服务器

**`/.well-known/oauth-authorization-server`**
- 返回 JSON，列出 `authorization_endpoint`、`token_endpoint`、`registration_endpoint`
- 必须声明 `code_challenge_methods_supported: ["S256"]`
- 必须声明 `grant_types_supported: ["authorization_code", "refresh_token"]`

**`/authorize`**
- 接收 `response_type=code`、`client_id`、`redirect_uri`、`state`、`code_challenge`、`code_challenge_method`、`resource`
- 展示授权页给用户
- 用户同意后，302 重定向到 `redirect_uri?code=xxx&state=xxx`

**`/token`**
- 接收 `grant_type=authorization_code`，验证 `code_verifier`（PKCE），验证 `resource`（RFC 8707），返回 `access_token` + `refresh_token`
- 接收 `grant_type=refresh_token`，验证 refresh_token，返回新的 access_token
- 建议支持 `client_secret_basic`（HTTP Basic Auth）鉴权方式

**`/register`**
- 接收 `client_name`、`redirect_uris`、`grant_types` 等
- 当场生成并返回 `client_id` 和 `client_secret`
- 不需要人工审核，立即生效

---

## 九、Notion vs Linear 关键差异一览

| | Notion MCP | Linear MCP |
|---|---|---|
| MCP Server URL | `https://mcp.notion.com/mcp` | `https://mcp.linear.app` |
| 授权服务器 issuer | `https://mcp.notion.com` | `https://mcp.linear.app` |
| PKCE 支持 | `plain` 和 `S256` | 仅 `S256` |
| SEP-991 CIMD | 不支持 | 支持 |
| transport 类型 | streamable_http | SSE（`/sse` 后缀） |
| scopes_supported | 响应里未声明 | 响应里未声明 |