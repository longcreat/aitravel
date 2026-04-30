ALTER TABLE chat_messages
ADD COLUMN parts_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE chat_messages
ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
CHECK (status IN ('streaming', 'completed', 'stopped', 'failed'));

ALTER TABLE assistant_message_versions
ADD COLUMN parts_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE assistant_message_versions
ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
CHECK (status IN ('streaming', 'completed', 'stopped', 'failed'));
