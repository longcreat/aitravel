# AI Agent Travel H5

基于 **LangChain + LangGraph + MCP + React + shadcn/ui** 的移动优先旅行对话应用。

## 技术栈

- 后端：Python 3.12, FastAPI, LangChain `1.2.15`, LangGraph `1.1.6`, langchain-mcp-adapters `0.2.2`
- 前端：React + Vite + TypeScript + Tailwind + shadcn/ui 风格组件

## 官方文档基线

- [LangChain Overview](https://docs.langchain.com/oss/python/langchain/overview)
- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain Structured Output](https://docs.langchain.com/oss/python/langchain/structured-output)
- [LangChain Short-term Memory](https://docs.langchain.com/oss/python/langchain/short-term-memory)
- [LangChain MCP](https://docs.langchain.com/oss/python/langchain/mcp)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

## 目录结构

```text
backend/
  app/
    agent/
    api/
    llm/
    mcp/
    memory/
    prompt/
    schemas/
    tool/
  config/
    mcp.servers.json
    mcp.servers.example.json
  tests/

frontend/
  src/
    app/
    features/
      chat/
      itinerary/
    shared/
      config/
      lib/
      ui/
    test/
```

## 后端启动

```bash
cd backend
python -m venv .venv
# Windows
.venv\\Scripts\\activate
pip install -e .[dev]
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

## 前端启动

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

## MCP 配置

主配置文件：`backend/config/mcp.servers.json`

- 当前默认 `{}`（空配置，保证可启动）
- 可参考 `backend/config/mcp.servers.example.json`
- 支持 `${ENV_VAR}` 注入
- 支持 `stdio` 与 `http`（会标准化为 `streamable_http`）

## API

- `GET /api/health`
- `POST /api/chat/stream`（SSE）

请求体：

```json
{
  "thread_id": "thread-123",
  "user_message": "帮我做5天大阪+京都行程，预算1万元",
  "locale": "zh-CN",
  "session_meta": {}
}
```

SSE 事件顺序：

- `start`
- `token`
- `tool_called` / `tool_returned`
- `final`
- `error`（仅异常时）
- `done`

## 测试

后端：

```bash
cd backend
pytest
```

前端：

```bash
cd frontend
npm run test
```
