-- 每个用户对每个 MCP connector 的 OAuth 授权与令牌
CREATE TABLE user_mcp_authorizations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  mcp_server_url TEXT NOT NULL,
  authorization_server TEXT,
  client_id TEXT,
  client_secret_enc TEXT,
  redirect_uri TEXT NOT NULL,
  access_token_enc TEXT,
  refresh_token_enc TEXT,
  token_type TEXT NOT NULL DEFAULT 'bearer',
  scope TEXT,
  expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'connected', 'expired', 'revoked', 'failed')),
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, connector_id),
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX idx_user_mcp_auth_user
  ON user_mcp_authorizations (user_id, status);

-- OAuth 流程中临时持有的 state / PKCE / nonce
CREATE TABLE connector_oauth_states (
  state TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  authorization_id TEXT NOT NULL,
  code_verifier TEXT NOT NULL,
  redirect_after TEXT,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  FOREIGN KEY (authorization_id) REFERENCES user_mcp_authorizations (id) ON DELETE CASCADE
);

CREATE INDEX idx_connector_oauth_states_user
  ON connector_oauth_states (user_id);
