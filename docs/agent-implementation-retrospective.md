# Agent 实现复盘笔记

## 1. 项目背景

这是一个移动优先的旅行 Agent 项目，目标不是做一个普通问答机器人，而是做一个能：

- 结合本地工具和 MCP 工具完成真实任务
- 支持多轮会话记忆
- 支持流式输出
- 支持工具调用过程可视化
- 在前端提供接近产品级的交互体验

当前核心技术栈：

- 后端：FastAPI + LangChain `1.2.15` + LangGraph `1.1.6`
- Agent：`create_agent(...)`
- 记忆：LangGraph SQLite checkpointer
- 工具：本地工具 + MCP 工具
- 前端：React + Vite + TypeScript

这份文档不是流水账，而是从“问题 / 思考过程 / 解决方案”角度整理的一份实现复盘，目标是后续面试时可以直接作为项目经验讲述材料。

---

## 2. Agent 架构与依赖选型

### 2.1 为什么选 `create_agent`

一开始的目标不是自己手写一套复杂状态机，而是先建立一条稳定的 Agent 主链路。因此核心思路是：

1. 用 `create_agent(...)` 快速搭出可执行 Agent
2. 用 LangGraph 官方 checkpointer 管短期记忆
3. 用 MCP 接入真实外部能力
4. 用 FastAPI + SSE 把 LangGraph 原生流透给前端

核心初始化链路大致是：

```python
model = build_chat_model()
local_tools = get_local_tools()
connections = load_mcp_connections(...)
mcp_bundle = await load_mcp_tools(connections)
checkpointer, store = await build_memory_runtime(...)

agent = create_agent(
    model=model,
    tools=[*local_tools, *mcp_bundle.tools],
    system_prompt=TRAVEL_SYSTEM_PROMPT,
    checkpointer=checkpointer,
    store=store,
)
```

### 2.2 为什么保留两层存储

项目里最终保留了两套“存储语义”：

1. **业务消息存储**
- 表：`chat_sessions`、`chat_messages`
- 用途：给前端展示历史对话

2. **Agent 运行时存储**
- 表：`checkpoints`、`writes`
- 用途：让 LangGraph 恢复 thread 状态

这是后面很多问题能被理清的前提。因为：

- 前端看到的“聊天记录”
- Agent 恢复上下文时用的“运行时状态”

它们不是一回事。

---

## 3. 问题分类复盘

## 3.1 命名语义问题：`create_agent` 返回对象却被叫成 `graph`

### 问题

项目初期在服务层里，`create_agent(...)` 的返回值被命名成了 `graph`。

这在技术上不算错，因为底层确实由 LangGraph 驱动，但从学习和协作角度看非常别扭：

- 使用者以为拿到的是“底层图对象”
- 实际对外语义上，它已经是“可执行 Agent”

### 思考过程

这里的关键不是“命名偏好”，而是**抽象层级一致性**。

如果代码里已经决定对外暴露的是：

- `TravelAgentService`
- `stream_invoke`
- `create_agent`

那这一层再把对象叫成 `graph`，会让阅读者在脑中来回切换“Agent 视角”和“LangGraph 内部视角”。

### 解决方案

把服务层这条运行链路统一改为：

- `AgentRuntime.agent`
- `agent = create_agent(...)`
- `self._runtime.agent.astream(...)`

只在注释里说明：

> 这是 Agent，对外语义按 Agent 理解；底层执行由 LangGraph 驱动。

### 面试表达

> 我在实现时专门收过一轮命名，把 `create_agent` 返回值从 `graph` 统一改成 `agent`。这不是表面样式问题，而是为了让代码抽象层级一致，降低后来维护和学习 LangGraph 时的认知切换成本。

---

## 3.2 流式协议问题：Provider 原生流 vs LangGraph 原生流

### 问题

最开始很容易把 Claude/OpenAI 这类模型厂商自己的 SSE 协议，和 LangGraph 的原生流混在一起。

比如用户看到的例子里会有：

- `message_start`
- `content_block_delta`
- `message_stop`

但项目实际采用的是：

- LangGraph `astream(..., stream_mode=["messages", "updates", "values"], version="v2")`

### 思考过程

如果目标是“学习 LangChain/LangGraph 原生流”，就不应该再自定义一套业务事件去包装掉底层结构。

否则会出现两个问题：

1. 看起来像在学 LangGraph，实际消费的是自己包装的协议
2. 一旦后续要调试 tool call / values / chunk，就会很难对照官方文档

### 解决方案

统一采用 LangGraph 原生流：

- `messages`
- `updates`
- `values`
- `error`

后端不再二次包装成：

- `token`
- `final`
- `tool_called`

而是直接把 `StreamPart` 序列化后透出给前端。

### 面试表达

> 这个项目我刻意保留了 LangGraph 原生流，而不是再包一层业务 SSE。这样做的好处是前后端调试可以直接对照官方事件语义，特别是在工具调用和最终 state 对齐时，复杂度会低很多。

---

## 3.3 工具调用问题：未闭合的 tool call 会污染整个线程

### 问题

工具调用链路里出现过一个很典型的问题：

- assistant 发出了 `tool_calls`
- 但对应 `ToolMessage` 还没回来
- 用户就中断/暂停/继续发下一条消息

这会导致 provider 直接报错：

> assistant message with tool_calls must be followed by tool messages...

### 思考过程

这里最关键的认知是：

**一轮工具调用不是“输出了一半文字”，而是一个事务。**

如果这轮事务中间被打断：

- 不能简单认为“只是暂停一下回答”
- 因为底层消息链已经进入了“半完成状态”

这也是为什么很多成熟 AI 产品看起来“暂停后还能继续对话”，但它们背后一定做了下面几类事情之一：

- 回滚到稳定点
- 把正在执行的 run 和正式对话历史分离
- 自动补齐取消态

### 解决方案

项目最后采用的是：

1. 每轮流式前记录稳定 checkpoint
2. 运行异常、中断、前端主动停止时，回滚到最近一个合法 checkpoint
3. 删除稳定点之后的脏 `checkpoints / writes`

这让“暂停”真正变成：

- 结束当前 run
- 但不污染整条会话

### 面试表达

> 这个项目里我踩到过一个典型 Agent 事务问题：如果 tool call 已经发出但 ToolMessage 没回来，直接继续复用同一线程，会把消息链污染掉。我最后是用 LangGraph 的 checkpoint 做回滚，把线程恢复到最近一个合法稳定点，从而把“暂停”从 UI 行为提升成了真正的运行时事务控制。

---

## 3.4 状态恢复问题：业务消息历史和 Agent checkpoint 不是一回事

### 问题

用户很容易问：

> 这些内容到底存数据库了吗？

尤其是在看到：

- `AIMessage.tool_calls`
- `ToolMessage`
- `values.messages`

这类内容的时候，很容易误以为它们都应该直接出现在业务消息表里。

### 思考过程

这里必须先分清两层：

1. **业务视角**
- 用户消息
- 最终助手回复
- 用于会话历史展示

2. **运行时视角**
- Tool call
- Tool result
- 当前 graph state
- 用于恢复 Agent 上下文

这两者如果不分开，后续无论是历史恢复、回滚还是前端展示都会乱。

### 解决方案

最终方案是：

- `chat_messages` 只存用户消息和最终 assistant 正文
- `checkpoints / writes` 存 LangGraph 运行状态
- 需要向前端展示的工具轨迹、处理中间过程，作为 `meta_json` 的一部分附着在最终 assistant 消息上

这让：

- 历史展示
- Agent 恢复
- 元信息

三条链路都能各归其位。

### 面试表达

> 我在存储设计上没有把 LangGraph checkpoint 和业务消息表混为一谈。业务表只存用户和最终回复，checkpoint 负责运行时恢复，而工具轨迹和处理中间过程走 meta 附加字段。这样历史展示和 Agent 记忆各自职责清晰，后续排障也会轻很多。

---

## 3.5 MCP 接入问题：配置格式严格，错误往往发生在启动阶段

### 问题

在接入高德 MCP 的时候，服务启动直接失败了，报的是 Pydantic 校验错误：

- `transport` 缺失
- `url` 缺失

看上去像 MCP 服务挂了，实际不是。

### 思考过程

问题核心不在 MCP 本身，而在于：

- 配置解析器定义的是强类型联合
- 每条连接配置必须显式说明 `transport`

也就是说，像下面这种看似直觉的配置：

```json
{
  "command": "uvx",
  "args": ["amap-mcp-server"]
}
```

在当前实现里其实是非法的。

### 解决方案

把配置显式写成：

```json
{
  "transport": "stdio",
  "command": "uvx",
  "args": ["amap-mcp-server"],
  "env": {
    "AMAP_MAPS_API_KEY": "${AMAP_MAPS_API_KEY}"
  }
}
```

同时保留 `${ENV_VAR}` 注入能力，避免把 key 写死到配置文件里。

### 面试表达

> 我们的 MCP 配置不是弱约束 JSON，而是经过 Pydantic 强校验的联合类型。这个好处是启动时就能把 transport、url、stdio 这些配置问题提前暴露，不会把错误拖到运行期才发现。

---

## 3.6 序列化问题：自定义类型进入 checkpoint 会触发反序列化告警

### 问题

早期项目里曾用过结构化输出类型，比如 `StructuredTravelPlan`。

LangGraph checkpoint 在恢复时出现过类似告警：

> Deserializing unregistered type ... from checkpoint

### 思考过程

这类问题表面上是 warning，本质上是：

- 运行时状态里混进了自定义类型
- 但序列化器没有明确把它加入 allowlist

如果未来版本变严格，这种 warning 很可能会升级成真正的恢复失败。

### 解决方案

后来项目直接做了两步收敛：

1. 彻底移除结构化行程卡片方案
2. 让 Agent 最终只输出纯文本 assistant_message

这样既让产品形态变简单，也减少了 checkpoint 里自定义类型的维护成本。

### 面试表达

> 我们曾经尝试过结构化输出，但后来发现对当前产品阶段来说，纯文本 + meta 更合适。这样不光简化了前端渲染，也规避了自定义类型进入 LangGraph checkpoint 带来的序列化和恢复风险。

---

## 3.7 前端流式展示问题：中间过程和最终答案被混成了一个气泡

### 问题

用户会看到这种现象：

1. 先出现“我来帮您查找……”
2. 然后变成“让我再搜索……”
3. 最后又被完整答案覆盖

看起来像：

- 模型来回改口
- 页面反复抖动
- 早先文字又“消失了”

### 思考过程

复盘后发现，问题不在模型，而在前端聚合策略：

- `messages` 事件里的所有 chunk 都被直接 `+=` 到同一个正文
- `updates` 再补工具轨迹
- `values` 又把同一个气泡整体覆盖成最终答案

而后端最终持久化时，本来就只认：

- 最后一个稳定 AIMessage

所以页面上的“多次变化”其实是：

- 临时过程先展示
- 最终状态再覆盖

### 解决方案

这部分后来做过两轮尝试：

1. 先把 assistant 气泡拆成“处理过程 + 最终答案”两层
2. 最终又回退成单气泡 LangChain 原型流式输出

原因是第二轮产品选择更偏向“看到什么就流出来什么”，不再单独展示中间过程。

### 面试表达

> 这个项目里我做过一次比较关键的流式状态机重构。最初所有 AI chunk 都被直接拼进同一个正文，后面我一度尝试把工具前言拆成单独区域，但最终还是按产品选择回到单气泡流式输出。这个过程让我更明确了一个点：流式展示策略不是纯技术问题，最终要服从产品对“过程可见性”和“阅读连续性”的取舍。

---

## 3.8 UI/产品协同问题：中间过程不等于私有 CoT

### 问题

当我们决定把中间文案收起来时，会遇到一个很容易答错的问题：

> 这些内容到底该不该叫“思考内容”？

### 思考过程

这里要区分两件事：

1. 模型私有推理（private CoT）
2. 工具调用前后的公开工作文案

当前项目里看到的其实是后者：

- “我先帮你搜一下”
- “让我再试试更具体的关键词”

这些内容不是模型私有 CoT，但也不适合作为最终回答正文。

### 解决方案

这套命名后来没有继续保留到最终产品里，但这次讨论仍然很有价值。我们的共识是：

- 公开工作文案不能直接叫“思考内容”
- 因为它不是私有 CoT，而是对用户可见的工作流前言

### 面试表达

> 我们当时专门讨论过“工具前的中间文案该怎么命名”，结论是它不能直接叫“思考内容”，因为那会混淆公开工作流文案和私有 CoT。哪怕后来产品决定不单独展示这部分，这个命名判断本身仍然很重要。

---

## 3.9 工程化问题：开发环境热重载把 `.venv` 也监控进来了

### 问题

开发阶段出现过一种很诡异的现象：

- Uvicorn 不断重启
- 日志一直显示 `.venv/site-packages/openai/...` 有变化

### 思考过程

根因不是业务代码，而是：

- 后端开了 `--reload`
- 虚拟环境就在 `backend/.venv`
- WatchFiles 把 `.venv` 也当成源码目录监控了

### 解决方案

把开发启动命令收敛成只监听：

- `app`
- `config`

也就是：

```bash
uvicorn app.main:create_app --factory --reload --reload-dir app --reload-dir config
```

而不是让它监控整个 `backend` 目录。

### 面试表达

> 这个项目里我还顺手修过一个挺典型的工程化问题：热重载把虚拟环境当成源码目录一起监听，导致服务反复重启。最后是把 reload 范围收窄到 app 和 config，开发体验稳定了很多。

---

## 3.10 认证持久化问题：前端重启后被误判成掉登录

### 问题

前端重启后，用户会发现自己“好像掉登录了”。

### 思考过程

起初直觉会怀疑：

- token 没存下来
- localStorage 被清了

但复盘发现并不是存储问题，而是启动恢复逻辑太激进：

- 前端启动后会调用 `/api/auth/me`
- 只要失败，就直接清 token

这会把：

- 网络瞬时失败
- 后端热重启
- 500

都误判成“认证失效”。

### 解决方案

修成：

- 只有 `/api/auth/me` 返回 `401/403` 才清 token
- 其他失败只保留缓存态，不强制登出

### 面试表达

> 我还处理过一个前端认证恢复 bug。问题不在 token 存储，而在“请求 /me 失败就立刻清 token”的策略太激进。后来改成只有 401/403 才真正登出，其他异常保留缓存态，这类开发环境和弱网下的误掉登录问题就消失了。

---

## 4. 这套 Agent 实现的核心经验

如果把整个项目压缩成几条关键经验，我会总结成下面 5 句：

1. **Agent 不是单次调用，而是带事务边界的状态机**
- 特别是 tool call 出现以后，中断和恢复必须按事务处理

2. **业务历史和运行时 checkpoint 必须分层**
- 一个给用户看
- 一个给 Agent 恢复

3. **流式展示不能简单拼 token，要区分最终答案和中间过程**
- 否则前端一定会抖

4. **MCP 接入的主要难点不在“调用”，而在“配置、启动校验和错误暴露”**

5. **产品层的命名和边界要跟技术语义一致**
- 例如公开工作文案不等于“思考内容”

---

## 5. 面试时可以直接讲的版本

下面这段可以直接作为项目复盘回答模板：

> 这个项目我做的是一个基于 LangChain、LangGraph 和 MCP 的旅行 Agent。实现过程中我重点解决了三类问题。  
> 第一类是 **运行时状态问题**，比如 tool call 中断会污染线程，我最后用 LangGraph checkpoint 做回滚，把每轮执行当成事务处理。  
> 第二类是 **流式展示问题**，早期所有 chunk 都直接拼到一个气泡里，导致中间工具前言和最终答案混在一起。中间我尝试过把它拆层展示，但最终还是按产品取舍回到单气泡流式输出。  
> 第三类是 **工程化和接入问题**，比如 MCP 配置校验、SQLite 双层存储、前端认证恢复、热重载误监听 `.venv`。  
> 这套项目让我最大的收获是，Agent 真正难的不是把模型调起来，而是把状态、工具、流式和产品体验四条链路一起收敛成一个稳定系统。

---

## 6. 后续如果继续优化，我会优先做什么

1. 给 tool trace 增加更明确的结构化状态，比如 `searching / calling / returned / summarizing`
2. 把 FastAPI 的 `on_event` 迁到 lifespan，消掉启动 warning
3. 按页面和功能做前端 chunk 拆分，解决当前 build 的大 chunk warning

---

## 7. 一句话总结

这个项目最有价值的部分，不是“我把 LangChain 跑起来了”，而是：

> 我把一个带工具调用、带状态恢复、带流式输出、带前端产品交互的 Agent 系统，从 demo 级别收敛到了可以稳定对话和可解释排障的工程状态。
