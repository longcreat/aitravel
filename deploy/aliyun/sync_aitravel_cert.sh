#!/bin/sh
set -eu

BASE_DIR="/root/aitravel/deploy/aliyun"
OPENRESTY_CONF_DIR="/opt/1panel/apps/openresty/openresty/conf/conf.d"
OPENRESTY_CERT_DIR="/opt/1panel/apps/openresty/openresty/www/certs/aitravel.aigoway.tech"

python3 "$BASE_DIR/export_1panel_ssl.py" \
  --domain '*.aigoway.tech' \
  --out-dir "$OPENRESTY_CERT_DIR"

cp "$BASE_DIR/openresty-aitravel.aigoway.tech.conf" \
  "$OPENRESTY_CONF_DIR/aitravel.aigoway.tech.conf"

docker exec 1Panel-openresty-VDZj sh -lc '/usr/local/openresty/bin/openresty -t && /usr/local/openresty/bin/openresty -s reload'
