# 语音输入（按住说话）产品方案

> 版本：v1.0（2026-09-13）
> 适用范围：WANDER AI 移动端聊天（H5）
> 状态：与代码现状一致（分支 `feature/alipay-subscription`，前端 `use-voice-input.ts` / `use-voice-utterances.ts` / `chat-composer.tsx` / `chat-page.tsx`，后端 `app/speech/stt.py` / `app/api/stt_ws.py`）

---

## 1. 功能逻辑与交互

### 1.1 功能概述

在聊天输入框提供"按住说话"的语音输入模式：用户按住麦克风条说话，实时建立 WebSocket 流式识别；松手后语音转写为文字并自动发送给 AI Agent，AI 开始流式回复。转写未完成时聊天区显示等待动画，完成后无缝替换为真实消息。

产品定位：微信式按住说话 + 自动发送，面向移动端 C 端用户，核心目标是**松手即出字**（实测松手到最终文本约 0.2 秒）。

### 1.2 入口与模式切换

- 输入框右侧麦克风图标：文本模式 ⇄ 语音模式切换，切换为纯前端状态（`chat-composer.tsx` 内 `mode` state）。
- 语音模式下，bar 右侧保留键盘图标可切回文本；切换时若有进行中的录音会立即取消（已松手、尚在转写中的话语**不受影响**，会继续完成并发送）。

### 1.3 交互状态机

| 状态 | 视觉 | 进入条件 | 退出 |
|---|---|---|---|
| 待机 idle | 浅灰 bar「按住 说话」+ 麦克风图标 | 初始 / 松手后 / 取消后 | 手指按下 |
| 录音中 recording（含连接期） | 深色 bar（bg-ink）+ 4 根白色均衡器竖条（CSS 错相位动画）+「正在聆听，松开发送…」 | 手指按下（`starting` 与 `recording` 视觉合并，建连过程对用户无感） | 松手 / 上滑 / 切换模式 |
| 取消提示 cancel-armed | 红色 bar（#b95a46）+「↑ 松开取消」 | 录音中手指上滑，超出 bar 顶边 12px | 滑回恢复录音态；在取消区松手 = 丢弃 |
| 错误 error | bar 内联红字错误信息 | 麦克风权限拒绝 / 连接失败等（未松手阶段的失败） | 下次按下时清除 |

### 1.4 核心交互细节

**按下**：立即进入录音态视觉；客户端同步开始 WebSocket 建连 + 麦克风采集，建连前产生的音频帧进入预缓冲（防止丢失前半段语音）。

**说话中**：
- 实时转写文本**不**上屏（产品决策：bar 显示固定文案，避免文字跳变干扰）；
- 服务端 partial 结果照常接收，仅用于异常兜底。

**松手（bar 内）**：
1. 输入条**立即复位**为待机，可马上再次按住说下一句；
2. 聊天区消息列表尾部出现**用户侧等待气泡**（typing-dots 动画，与等待 AI 回复同款），一条话语一个气泡；
3. 转写完成（实测约 0.2s）→ 气泡消失，真实用户消息 + AI 流式回复出现；
4. 松手时转写已完成则跳过气泡直接发送，无闪烁。

**连续说话**：上一句转写/发送期间可立即录下一句；每句话独立会话，转写结果进入**串行发送队列**，在 AI 回复间隙按序逐条发出，保证消息顺序。录音与 AI 回复中也可并行。

**上滑取消**：录音中手指上滑超过阈值 → bar 变红色取消态；滑回恢复；在取消区松手 → 整句话丢弃，不产生气泡、不发送、无提示。

**误触保护**：管线未就绪就松手、或实际录音时长 < 350ms → 判定误触，丢弃并 toast「说话时间太短，请按住后讲话」。目的：避免麦克风开启瞬态噪声被 ASR 幻听成"嗯"等语气词发出去。

**异常与兜底**：

| 场景 | 行为 |
|---|---|
| 未登录按住 | bar 内联提示「请先登录后再使用语音输入」，不建连 |
| 麦克风权限拒绝 / 不支持录音 | bar 内联错误提示 |
| 采集静音（Chrome 非原生采样率 bug） | 自愈：1.5s 内全部帧近零（峰值 < 0.002 ≈ -54dBFS）→ 自动拆掉管线、用默认采样率重建，用户无感（控制台留 `[voice]` 诊断日志） |
| AudioContext suspended（iOS） | `resume()` 后校验 running，失败则报「麦克风初始化失败，请重试」 |
| 松手后 5s 无最终结果 | 有部分文本 → 按部分文本发送；无 → toast「语音识别超时，请重试」 |
| 转写为空 | toast「未识别到内容，请重试」（不静默吞掉） |
| 连接断开 / 服务端错误 | 已松手：有部分文本按部分发送，否则 toast 错误；录音中：bar 内联报错 |
| 切换会话 | 清空未发送的语音队列与等待气泡 |

**消息发送配额**：语音产生的消息与文本消息一致，发送时消耗 1 次对话额度（每日免费 10 次 + 购买次数包余额），STT 识别本身不消耗额度。额度不足时后端在流中返回错误，前端 toast 提示「今日免费次数已用完，请订阅次数包后继续」。

### 1.5 端到端时序（松手到出字）

```
用户松手
  → 前端发 {"action":"finish"}（同一 WS，音频帧之后，顺序保证）
  → 后端 conv.commit() 触发服务端 finalize
  → 阿里云返回 .completed（实测 ~150ms）
  → 后端转发 sentence{sentence_end:true} + done
  → 前端结算（松手后 ~0.17s）→ 等待气泡替换为真实消息 → Agent 流式回复
```

---

## 2. 后端实现逻辑

### 2.1 组件与职责

| 文件 | 职责 |
|---|---|
| `backend/app/api/stt_ws.py` | WebSocket 端点 `/api/stt/ws`：鉴权、帧转发、会话生命周期 |
| `backend/app/speech/stt.py` | `DashScopeSttSession`：封装阿里云百炼 OmniRealtimeConversation SDK，把 SDK 回调转为内部事件队列 |
| `backend/app/main.py` | 注册 stt 路由 |

一个浏览器 WS 连接 = 一次按住说话 = 一个 `DashScopeSttSession` = 一条阿里云 realtime 连接（该模型不支持连接复用）。

### 2.2 WS 协议（前端 ⇄ 后端）

连接：`GET /api/stt/ws?token=<JWT>`，鉴权失败关闭码 `4401`；未配置阿里云 Key 关闭 `4403`；会话启动失败关闭 `4402`。

| 方向 | 消息 | 说明 |
|---|---|---|
| 客户端 → 后端 | 二进制帧 | PCM 16kHz / 16bit / 单声道，前端约每 64ms 一帧（1024 样本 @16k） |
| 客户端 → 后端 | `{"action": "finish"}` | 松手信号，后端结束识别 |
| 后端 → 客户端 | `{"type": "sentence", "text", "sentence_end"}` | 实时部分结果（`text` = 已确认前缀 + stash 草稿拼接）与最终句 |
| 后端 → 客户端 | `{"type": "done", "text"}` | 完整结果（多段累积拼接后） |
| 后端 → 客户端 | `{"type": "error", "message"}` | 错误 |

### 2.3 阿里云对接（qwen3-asr-flash-realtime）

经官方 SDK `dashscope.audio.qwen_omni.OmniRealtimeConversation`（版本 ≥1.25.2），默认端点 `wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model=<model>`，可用 `ALIYUN_STT_MODEL` / `ALIYUN_STT_WS_URL` 覆盖；API Key 取 `ALIYUN_STT_API_KEY` → `ALIYUN_TTS_API_KEY` → `OPENAI_API_KEY`。

会话配置（`session.update`）：
- `output_modalities=[TEXT]`、`enable_input_audio_transcription=True`
- **`enable_turn_detection=False`（Manual 模式）**——官方文档明确该模式"由客户端通过 commit 控制断句，适用于聊天软件按住说话"的场景；VAD 模式不需要（且不适合）按住说话的语义
- `TranscriptionParams(language="zh", sample_rate=16000, input_audio_format="pcm")`

事件映射（官方协议 → 内部事件）：
- `conversation.item.input_audio_transcription.text`（`text` + `stash` 字段）→ `sentence{sentence_end:false}`，实时预览 = `text + stash` 拼接
- `conversation.item.input_audio_transcription.completed`（`transcript`）→ `sentence{sentence_end:true}`；若已松手（`_finishing`）同时立即下发 `done`
- `session.finished` → `done` 兜底
- `error` → `error`

**多段累积**：`_final_parts` 列表累积各段 transcript，`done.text = "".join(parts)`——绝不能逐句覆盖（VAD/多次 commit 场景会丢内容）。

### 2.4 结束流程（关键设计）

`finish()` 的实测约束与对策：

| 实测事实 | 对策 |
|---|---|
| commit 后 `.completed` 约 150ms 到达 | commit 后等待最终结果事件，最多 2.5s |
| `session.finished` 恒定在最后活动 ~6s 后才下发 | **不同步等待**（旧实现 `end_session(timeout=5)` 必然超时、每句白阻塞 5s）；拿到结果后 `end_session_async()` + 直接 `close()` |

流程：置 `_finishing` → `commit()`（触发 finalize，容错）→ 等 `_final_event` ≤2.5s → `end_session_async()` → `close()`。结果未到就关闭的场景由前端 5s 超时兜底。

降级路径：Omni 初始化异常时自动降级到 Legacy `Recognition`（Paraformer，`paraformer-realtime-v2`），同一套内部事件协议（测试环境 PYTEST 下强制走 legacy 以便离线测试）。

### 2.5 WS 端点主循环（stt_ws.py）

```
accept → 建 DashScopeSttSession → 启动 forward_task（事件队列→客户端）
loop: receive()
  ├─ 二进制帧 → session.send_audio_frame()
  └─ {"action":"finish"} → break
finally:
  await asyncio.to_thread(session.finish)      # 不阻塞事件循环
  await wait_for(forward_task, timeout=5)      # 排空剩余事件
  close websocket
```

### 2.6 实测性能数据（2026-09-13，端到端探针）

| 指标 | 数值 |
|---|---|
| 录音期间 partial 推送 | 流式到达，约每 1-2s 一批（服务端节奏） |
| 松手 → 最终文本（8s 语音） | **~0.17s**，内容完整 |
| 松手 → 最终文本（0.5s 短语音） | ~0.11s |
| commit 后 `.completed` | ~150ms |
| `session.finished` | 最后活动后 ~6s（因此不同步等待） |
| Manual 模式音频上限 | 官方建议单次会话 ≤60s |

---

## 3. 前端功能实现

### 3.1 模块划分

| 文件 | 职责 |
|---|---|
| `hooks/use-voice-input.ts` | 语音采集与识别状态机（按下/松手/取消、WS、音频管线、结算） |
| `hooks/use-voice-utterances.ts` | 等待气泡列表 + 串行发送队列 |
| `ui/chat-composer.tsx` | 语音 bar 渲染 + 指针手势（按住/上滑取消） |
| `ui/chat-page.tsx` | 持有两个 hook、渲染等待气泡、错误/失败 toast、自动滚动 |

架构原则：**按话语（utterance）隔离**。每句话从按下到出结果拥有独立的 WS 连接 + 音频管线 + 结算回调，互不共享可变状态；所有回调经 ref 分发，杜绝陈旧闭包。这是对旧版（全局单 WS + 6 个散落布尔量）交互 bug 频发的结构性修复。

### 3.2 采集状态机（useVoiceInput）

状态仅 `idle | starting | recording`（bar 视觉将 starting 与 recording 合并）。核心对象 `VoiceSession`：一次说话的全部上下文（socket、AudioContext、processor、pendingAudio、finalText、统计计数器、各定时器）。

**生命周期**：
- `press()`：校验登录 token → 建 WS（token 走 query）→ `getUserMedia`（echoCancellation+noiseSuppression）→ 建 AudioContext → ScriptProcessor(1024) 采集。就绪前的 PCM 帧进 `pendingAudio`，`onopen` 时补发。
- `release()`：误触保护（见 3.4）→ 状态立即回 idle（bar 复位）→ 会话转入 `inflight` 后台集合 → 回调 `onUtteranceStarted(id)`（挂等待气泡）→ 发送 finish。
- 松手后的会话继续自行收尾：`.completed` → `onUtteranceResolved(id, text)`；异常 → `onUtteranceFailed(id, message)`；结算后自动拆除。**多句并行**由此天然支持。
- `cancel()`：仅终止当前录音会话（上滑取消/切键盘），不触碰已松手的后台会话。
- 组件卸载：静默终止全部会话。

**结算优先级**（先到先结算，`settled` 标志防重）：
1. 松手后 `sentence_end=true`（`.completed`）→ 交付累积 `finalText`（多段拼接）；
2. `done` 事件 → 交付 `done.text`；
3. 断连/服务端错误 → 部分文本兜底交付，否则失败 toast；
4. 5s 超时 → 部分文本（`finalText + interimText`）交付，否则「语音识别超时，请重试」；
5. 空转写 → 明确失败「未识别到内容，请重试」（不静默吞掉）。

### 3.3 音频管线与静音自愈

- 采集：`new AudioContext({ sampleRate: 16000 })` 让浏览器原生重采样（自带抗混叠滤波，规避 JS 隔点降采样的高频折叠失真）；构造失败回退默认采样率 + JS 逐点抽取。
- 上下文防呆：`suspended` 状态先 `resume()`，仍非 running 则报「麦克风初始化失败」（iOS 非手势栈创建的 context 不会出音频）。
- **静音自愈**：Chrome 在部分 Windows 设备上，非原生采样率 context 的麦克风输入是近零死流（间歇性，症状为"发出去没内容"）。录音开始 1.5s 后检查帧能量：全部帧峰值 < 0.002（-54dBFS）→ 拆掉管线，用默认采样率 + JS 降采样重建，同一会话继续，用户无感；控制台留 `[voice]` 诊断日志。重建只试一次，二次静音走正常超时兜底。

### 3.4 误触保护

`release()` 时若管线未就绪（`recordingStartedAt === 0`）或实际录音时长 < `minRecordMs`（默认 350ms）：静默丢弃会话 + toast「说话时间太短，请按住后讲话」。防止麦克风开启瞬态噪声被 ASR 幻听成"嗯"发出。测试可传 `minRecordMs: 0` 关闭该保护。

### 3.5 等待气泡与串行发送队列（useVoiceUtterances）

- `started(id)` → `pendingIds` 追加，聊天区渲染右侧 typing-dots 气泡（复用 `typing-dot`/`fade-up` 动画）；
- `resolved(id, text)` → 文本入队（气泡保留，与后续真实消息无缝衔接）；
- 发送循环：`!loading && ready` 时出队调用 `sendMessage(text)`；accepted → 移除气泡（真实消息由 `turn.start` 渲染）；auth_required → 交由既有登录续发流程；blocked → 放回队头重试；
- `failed(id, message)` → 移除气泡；message 非空则 toast；
- 队列用 ref 存储 + 版本号 state 驱动 drain effect；`threadId` 变化时清空队列与气泡（防止串台）。

### 3.6 交互手势（chat-composer）

- Pointer Events + `setPointerCapture`，`touch-none`、禁用长按菜单，兼容移动端；
- 上滑取消：`pointermove` 中 `clientY < bar.top - 12px` 进入取消态，滑回恢复，`pointerup` 按当前区域决定 release/cancel，`pointercancel` 等同取消；
- 录音中按钮不因 AI 回复中（loading）禁用——连说靠发送队列保证顺序。

---

## 4. 已知限制与后续规划

| 项 | 说明 |
|---|---|
| 单句 ≤60s | Manual 模式官方建议，当前未做前端强制截断（超长会被服务端截断） |
| partial 节奏 | 录音中部分结果约 1-2s 一批，由服务端控制，暂无法调整 |
| `session.finished` ~6s 延迟 | 已绕过（不等待），但每次会话在服务端残留 ~6s 资源 |
| 上滑取消提示 | 纯颜色变化，无文字提示（产品简化决策） |
| 多语言 | 固定 `language="zh"`，中英混说可用，纯外语未优化 |
| 候选增强 | 真实音量波形（AnalyserNode）、录音时长显示、上滑取消动画、AudioWorklet 替代 ScriptProcessor |

## 5. 测试与验证基线

- 前端 vitest：`use-voice-input.test.tsx`（22 用例：建连、降采样、预缓冲、各结算路径、误触、静音自愈、快按、连说、取消、超时、断连）+ `use-voice-utterances.test.tsx`（6 用例：队列顺序、忙时排队、会话切换清空等）
- 后端 pytest：`test_speech_stt.py`（多段累积/兜底）、`test_stt_ws.py`（鉴权/全流程，legacy fake 路径）
- 协议探针（`.tmp/asr_probe*.py`、`.tmp/ws_relay_probe.py`）：直连阿里云与端到端两种模式，可随时复跑验证协议行为
