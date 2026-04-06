export interface ItineraryItem {
  day: number;
  city: string;
  activities: string[];
  notes?: string | null;
}

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
  itinerary: ItineraryItem[];
  followups: string[];
  debug: ChatDebugInfo;
}

export interface ChatChunkPayload {
  id: string | null;
  type: string | null;
  content: unknown;
  name: string | null;
  chunk_position: unknown;
  tool_call_chunks: unknown[];
  tool_calls: unknown[];
  invalid_tool_calls: unknown[];
  usage_metadata: unknown;
  response_metadata: Record<string, unknown>;
  additional_kwargs: Record<string, unknown>;
}

export interface ChatChunkMeta {
  node: string | null;
  sequence: number;
  emitted_at: string;
}

export interface ChatChunkFrame {
  chunk: ChatChunkPayload;
  meta: ChatChunkMeta;
}

export type ChatStreamEvent =
  | {
      event: "start";
      data: {
        thread_id: string;
        started_at: string;
      };
    }
  | {
      event: "token";
      data: ChatChunkFrame;
    }
  | {
      event: "tool_called" | "tool_returned";
      data: {
        tool_name: string;
        payload: unknown;
      };
    }
  | {
      event: "final";
      data: ChatFinalPayload;
    }
  | {
      event: "error";
      data: {
        message: string;
      };
    }
  | {
      event: "done";
      data: Record<string, never>;
    };

export type ChatRole = "user" | "assistant";

export interface ChatMessageItem {
  id: string;
  role: ChatRole;
  text: string;
  chunk_frames?: ChatChunkFrame[];
  itinerary?: ItineraryItem[];
  followups?: string[];
  debug?: ChatDebugInfo;
}

export interface PersistedChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  itinerary: ItineraryItem[];
  followups: string[];
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
