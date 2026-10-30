#!/bin/sh
set -eu

: "${CLICKHOUSE_PASSWORD:?set CLICKHOUSE_PASSWORD}"

mkdir -p /var/lib/clickhouse/tmp /var/lib/clickhouse/user_files /var/lib/clickhouse/access /var/log/clickhouse-server
chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server
password_hash=$(printf %s "$CLICKHOUSE_PASSWORD" | sha256sum | cut -d ' ' -f 1)
cat > /etc/clickhouse-server/users.xml <<EOF
<clickhouse>
    <users>
        <default>
            <password_sha256_hex>${password_hash}</password_sha256_hex>
            <networks><ip>::/0</ip></networks>
            <profile>default</profile>
            <quota>default</quota>
            <access_management>1</access_management>
        </default>
    </users>
    <profiles><default /></profiles>
    <quotas><default /></quotas>
</clickhouse>
EOF
chown clickhouse:clickhouse /etc/clickhouse-server/users.xml
exec runuser -u clickhouse -- /usr/bin/clickhouse server --config-file=/etc/clickhouse-server/config.xml -- --listen_host=0.0.0.0
