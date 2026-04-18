export interface ToolTrace {
  phase: "called" | "returned";
  tool_name: string;
  payload: unknown;
  tool_call_id?: string | null;
  result_status?: "success" | "error" | null;
}

export interface StepDetailItem {
  id: string;
  tool_name: string;
  status: "running" | "success" | "error";
  summary: string;
}

export interface StepGroup {
  id: string;
  items: StepDetailItem[];
}

export type ChatRenderSegment =
  | {
      type: "text";
      text: string;
    }
  | {
      type: "step";
      step_group_id: string;
    };

export interface ChatMetaInfo {
  tool_traces: ToolTrace[];
  step_groups: StepGroup[];
  render_segments: ChatRenderSegment[];
  reasoning_text?: string | null;
  reasoning_state?: "streaming" | "completed" | null;
  mcp_connected_servers: string[];
  mcp_errors: string[];
}

export type AssistantVersionFeedback = "up" | "down" | null;

export interface AssistantMessageVersion {
  id: number;
  version_index: 1 | 2 | 3;
  kind: "original" | "regenerated";
  text: string;
  meta: ChatMetaInfo | null;
  feedback: AssistantVersionFeedback;
  created_at: string;
}

export interface ChatInvokeRequest {
  thread_id: string;
  user_message: string;
  locale: string;
  model_profile_key?: string | null;
  session_meta: Record<string, unknown>;
}

export interface ChatFinalPayload {
  assistant_message: string;
  meta: ChatMetaInfo;
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
  meta?: ChatMetaInfo;
  current_version_id?: number | null;
  versions?: AssistantMessageVersion[];
  can_regenerate?: boolean;
}

export interface PersistedChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  meta: ChatMetaInfo | null;
  reply_to_message_id?: number | null;
  current_version_id?: number | null;
  versions?: AssistantMessageVersion[];
  can_regenerate?: boolean;
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
  model_profile_key: string;
  messages: PersistedChatMessage[];
}

export type ChatModelProfileKind = "standard" | "thinking";

export interface ChatModelProfile {
  key: string;
  label: string;
  kind: ChatModelProfileKind;
  is_default: boolean;
}

export interface ListChatModelProfilesResponse {
  default_profile_key: string;
  profiles: ChatModelProfile[];
}

export interface UpdateSessionModelProfileRequest {
  model_profile_key: string;
}

export interface SessionModelProfileState {
  thread_id: string;
  model_profile_key: string;
}

export interface SwitchAssistantVersionRequest {
  version_id: number;
}

export interface UpdateAssistantFeedbackRequest {
  feedback: AssistantVersionFeedback;
}

export type SendIntentResult =
  | {
      status: "accepted";
      message: string;
    }
  | {
      status: "auth_required";
      message: string;
    }
  | {
      status: "blocked";
      reason: "empty" | "loading" | "not_ready";
    };
