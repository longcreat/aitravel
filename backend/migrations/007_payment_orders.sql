-- 支付订单
CREATE TABLE payment_orders (
  out_trade_no TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  package_id TEXT NOT NULL,
  amount TEXT NOT NULL,
  quota INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'PAID', 'CLOSED', 'REFUNDED')),
  created_at TEXT NOT NULL,
  paid_at TEXT,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX idx_payment_orders_user
  ON payment_orders (user_id, status);

-- 用户对话次数额度
CREATE TABLE user_quota (
  user_id TEXT PRIMARY KEY,
  remain_count INTEGER NOT NULL DEFAULT 0,
  free_date TEXT NOT NULL DEFAULT '',
  free_used INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
