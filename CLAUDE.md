# AI Travel Agent 项目开发与部署规范 (CLAUDE.md)

本项目是一个移动优先的智能旅行规划 Agent 应用，采用现代微服务与动静分离架构。

---

## 架构概览与域名资产

| 角色 | 域名 / 地址 | 托管位置 | 说明 |
| :--- | :--- | :--- | :--- |
| **前端 H5 应用** | `https://travel.aigoway.tech` | **Cloudflare Pages** | 全球 300+ 边缘机房 CDN 极速托管，零占用服务器带宽 |
| **后端 API 服务** | `https://api.aigoway.tech` | **阿里云 Docker** (`8.220.151.206:18000`) | FastAPI + LangChain/LangGraph + MCP，由 Cloudflare 高防代理 |

### 核心前后端通信机制
- **同源边缘网关代理**：前端页面发起的 `/api/*` 请求，直接由 Cloudflare Pages Functions（位于 `frontend/functions/api/[[path]].js`）在边缘节点透明代理至 `https://api.aigoway.tech/api/*`。
- **免跨域 (Zero CORS)**：前端代码中 `VITE_API_BASE_URL` 保持使用相对路径 `/api`，不要硬编码外部后端域名。

---

## 前端开发与部署规则

### 1. 本地运行
```bash
cd frontend
npm install
npm run dev
```

### 2. 前端唯一部署方式（重要！）
> ⚠️ **严禁将前端代码或构建产物（dist）拷贝到阿里云服务器！** 阿里云服务器仅作为纯后端计算节点，不承担前端静态文件托管。

部署前端仅需在 `frontend` 目录下运行：
```bash
cd frontend
npm run deploy
```
*底层命令已封装为：`tsc -b && vite build && npx wrangler pages deploy dist --project-name=aitravel --branch=main --commit-dirty=true`*。执行后 10 秒内自动全球上线并刷新 CDN。

---

## 后端开发与部署规则

### 1. 本地运行
```bash
cd backend
uv sync --frozen --extra dev
uv run --frozen uvicorn app.main:create_app --factory --reload --host localhost --port 8000
```

### 2. 后端部署
- 部署目录：阿里云 `/root/aitravel/backend`
- 运行形态：Docker 容器 `aitravel-backend`，映射宿主机端口 `127.0.0.1:18000 -> 8000`
- Nginx 反代配置：已在服务器端 OpenResty 直接运行，将 `api.aigoway.tech` 代理至 `127.0.0.1:18000`
- 更新后端代码：在服务器端 git pull 或同步后，执行 `docker restart aitravel-backend`

---

## 常用测试命令
- 前端测试：`cd frontend && npm run test`
- 后端测试：`cd backend && uv run --frozen --extra dev pytest`
- 线上健康检查：`curl https://travel.aigoway.tech/api/health` 或 `curl https://api.aigoway.tech/api/health`
