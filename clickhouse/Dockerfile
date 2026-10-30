FROM alpine:3.21.3 AS download
ARG CLICKHOUSE_VERSION=25.8.4.13
ARG CLICKHOUSE_PACKAGE_SHA512=4f82057b3c4f3b53b7aa3a721a4efa6dc9a4329aa49057ff44c44473a20b8708f599b7c2e6f79bda59cd985f5c60a203deaf6ed16b922aa5c23eb9f28c4ceae5
RUN apk add --no-cache curl \
    && curl -fL --retry 10 --retry-delay 2 --max-time 1800 \
        -o /tmp/clickhouse.tgz \
        "https://repo.clickhouse.com/tgz/stable/clickhouse-common-static-${CLICKHOUSE_VERSION}-amd64.tgz" \
    && echo "${CLICKHOUSE_PACKAGE_SHA512}  /tmp/clickhouse.tgz" | sha512sum -c \
    && mkdir -p /opt/clickhouse \
    && tar -xzf /tmp/clickhouse.tgz -C /opt/clickhouse --strip-components=1

FROM debian:12.10-slim
RUN groupadd --gid 10001 clickhouse \
    && useradd --uid 10001 --gid clickhouse --no-create-home clickhouse \
    && mkdir -p /etc/clickhouse-server /var/lib/clickhouse /var/log/clickhouse-server \
    && chown -R clickhouse:clickhouse /var/lib/clickhouse /var/log/clickhouse-server
COPY --from=download /opt/clickhouse/usr/bin/clickhouse /usr/bin/clickhouse
COPY clickhouse/config.xml /etc/clickhouse-server/config.xml
COPY clickhouse/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh && ln -s /usr/bin/clickhouse /usr/bin/clickhouse-client
EXPOSE 8123 9000 9004
ENTRYPOINT ["/entrypoint.sh"]
