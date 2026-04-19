ALTER TABLE chat_sessions
ADD COLUMN last_message_preview TEXT NOT NULL DEFAULT '';

ALTER TABLE chat_sessions
ADD COLUMN model_profile_key TEXT NOT NULL DEFAULT 'standard';

ALTER TABLE chat_sessions
ADD COLUMN stable_checkpoint_id TEXT;

ALTER TABLE chat_messages
ADD COLUMN current_version_id TEXT;

CREATE TABLE assistant_message_versions (
  id TEXT PRIMARY KEY,
  assistant_message_id TEXT NOT NULL,
  version_index INTEGER NOT NULL CHECK (version_index BETWEEN 1 AND 3),
  kind TEXT NOT NULL CHECK (kind IN ('original', 'regenerated')),
  text TEXT NOT NULL,
  meta_json TEXT,
  feedback TEXT CHECK (feedback IN ('up', 'down') OR feedback IS NULL),
  parent_checkpoint_id TEXT,
  result_checkpoint_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
  UNIQUE (assistant_message_id, version_index)
);

CREATE INDEX idx_assistant_message_versions_message_id
ON assistant_message_versions (assistant_message_id);
