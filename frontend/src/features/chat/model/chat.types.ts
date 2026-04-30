export interface ChatMetaInfo {
  mcp_connected_servers: string[];
  mcp_errors: string[];
}

export type AssistantVersionFeedback = "up" | "down" | null;
export type AssistantVersionSpeechStatus = "generating" | "ready" | "failed" | null;
export type ChatMessageStatus = "streaming" | "completed" | "stopped" | "failed";

export type ChatMessagePart =
  | {
      id: string;
      type: "text";
      text: string;
      status: ChatMessageStatus;
    }
  | {
      id: string;
      type: "reasoning";
      text: string;
      status: ChatMessageStatus;
    }
  | {
      id: string;
      type: "tool";
      tool_call_id: string;
      tool_name: string;
      input?: unknown;
      output?: unknown;
      status: "running" | "success" | "error";
    };

export interface AssistantMessageVersion {
  id: string;
  version_index: 1 | 2 | 3;
  kind: "original" | "regenerated";
  text: string;
  parts?: ChatMessagePart[];
  status?: ChatMessageStatus;
  meta: ChatMetaInfo | null;
  feedback: AssistantVersionFeedback;
  speech_status: AssistantVersionSpeechStatus;
  speech_mime_type?: string | null;
  created_at: string;
}

export interface ChatInvokeRequest {
  thread_id: string;
  user_message: string;
  locale: string;
  model_profile_key?: string | null;
  session_meta: Record<string, unknown>;
}

export type ChatStreamEvent =
  | {
      event: "turn.start";
      data: {
        thread_id: string;
        user_message?: PersistedChatMessage | null;
        assistant_message: PersistedChatMessage;
      };
    }
  | {
      event: "part.delta";
      data: {
        message_id: string;
        version_id: string;
        part_id: string;
        part_type: "text" | "reasoning";
        text_delta: string;
        status: ChatMessageStatus;
      };
    }
  | {
      event: "tool.start" | "tool.done";
      data: {
        message_id: string;
        version_id: string;
        part: Extract<ChatMessagePart, { type: "tool" }>;
      };
    }
  | {
      event: "message.completed";
      data: {
        message: PersistedChatMessage;
      };
    }
  | {
      event: "turn.done";
      data: {
        thread_id: string;
      };
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
  parts?: ChatMessagePart[];
  status?: ChatMessageStatus;
  meta?: ChatMetaInfo;
  current_version_id?: string | null;
  versions?: AssistantMessageVersion[];
  can_regenerate?: boolean;
}

export interface PersistedChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  parts: ChatMessagePart[];
  status: ChatMessageStatus;
  meta: ChatMetaInfo | null;
  reply_to_message_id?: string | null;
  current_version_id?: string | null;
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
  version_id: string;
}

export interface UpdateAssistantFeedbackRequest {
  feedback: AssistantVersionFeedback;
}

export interface SpeechPlaybackUrlResponse {
  playback_url: string;
  speech_status: Exclude<AssistantVersionSpeechStatus, "failed" | null>;
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
