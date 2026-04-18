CREATE TABLE chat_sessions (
  thread_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  custom_title INTEGER NOT NULL DEFAULT 0 CHECK (custom_title IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_chat_sessions_user_updated
ON chat_sessions (user_id, updated_at);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  text TEXT NOT NULL,
  meta_json TEXT,
  reply_to_message_id INTEGER,
  created_at TEXT NOT NULL,
  FOREIGN KEY (thread_id) REFERENCES chat_sessions(thread_id) ON DELETE CASCADE,
  FOREIGN KEY (reply_to_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL
);

CREATE INDEX idx_chat_messages_thread_id_id
ON chat_messages (thread_id, id);
