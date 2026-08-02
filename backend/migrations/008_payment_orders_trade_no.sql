-- 支付订单增加支付宝交易号
ALTER TABLE payment_orders ADD COLUMN trade_no TEXT;
