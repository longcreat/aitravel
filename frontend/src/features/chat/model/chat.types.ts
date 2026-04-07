export interface ToolTrace {
  phase: "called" | "returned";
  tool_name: string;
  payload: unknown;
}

export interface ChatDebugInfo {
  tool_traces: ToolTrace[];
  mcp_connected_servers: string[];
  mcp_errors: string[];
}

export interface ChatInvokeRequest {
  thread_id: string;
  user_message: string;
  locale: string;
  session_meta: Record<string, unknown>;
}

export interface ChatFinalPayload {
  assistant_message: string;
  debug: ChatDebugInfo;
}

export interface SerializedLangChainMessage {
  type: string;
  data: {
    content?: unknown;
    additional_kwargs?: Record<string, unknown>;
    response_metadata?: Record<string, unknown>;
    type?: string | null;
    name?: string | null;
    id?: string | null;
    tool_calls?: Array<{
      name?: string;
      args?: unknown;
      id?: string;
      type?: string;
    }>;
    invalid_tool_calls?: unknown[];
    usage_metadata?: unknown;
    tool_call_chunks?: unknown[];
    chunk_position?: unknown;
    tool_call_id?: string;
    artifact?: unknown;
    status?: string;
  };
}

export interface LangGraphStreamPart {
  type: "messages" | "updates" | "values" | string;
  ns: string[];
  data: unknown;
  interrupts?: unknown;
}

export type ChatStreamEvent =
  | {
      event: "messages" | "updates" | "values";
      data: LangGraphStreamPart;
    }
  | {
      event: "error";
      data: {
        message: string;
      };
    };

export type ChatRole = "user" | "assistant";

export interface ChatMessageItem {
  id: string;
  role: ChatRole;
  text: string;
  status?: "streaming" | "stopped";
  debug?: ChatDebugInfo;
}

export interface PersistedChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  debug: ChatDebugInfo | null;
  created_at: string;
}

export interface SessionSummary {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  last_message_preview: string;
}

export interface SessionDetail {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: PersistedChatMessage[];
}
