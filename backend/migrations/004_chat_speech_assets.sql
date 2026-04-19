CREATE TABLE assistant_version_speech_assets (
  id TEXT PRIMARY KEY,
  assistant_message_version_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('generating', 'ready', 'failed')),
  mime_type TEXT,
  object_key TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (assistant_message_version_id) REFERENCES assistant_message_versions(id) ON DELETE CASCADE
);

CREATE INDEX idx_assistant_version_speech_assets_version_id
ON assistant_version_speech_assets (assistant_message_version_id);
