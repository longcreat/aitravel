import { http } from "@/shared/lib/http";

export type ConnectorStatus =
  | "disconnected"
  | "pending"
  | "connected"
  | "expired"
  | "revoked"
  | "failed";

export interface ConnectorState {
  id: string;
  display_name: string;
  description: string;
  icon_url: string | null;
  mcp_server_url: string;
  enabled: boolean;
  status: ConnectorStatus;
  connected_at: string | null;
  last_error: string | null;
}

export interface ListConnectorsResponse {
  connectors: ConnectorState[];
}

export interface StartAuthorizationResponse {
  authorize_url: string;
  state: string;
  expires_in: number;
}

export const connectorsApi = {
  list: () => http.get<ListConnectorsResponse>("/api/connectors"),
  startAuthorization: (connectorId: string) =>
    http.post<StartAuthorizationResponse>(`/api/connectors/${encodeURIComponent(connectorId)}/authorize`),
  disconnect: (connectorId: string) =>
    http.delete<ConnectorState>(`/api/connectors/${encodeURIComponent(connectorId)}`),
};
