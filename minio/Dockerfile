FROM golang:1.25.0-alpine AS build
ARG MINIO_VERSION=RELEASE.2025-09-07T16-13-09Z
ARG GOPROXY=https://proxy.golang.org,direct
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    GOPROXY="$GOPROXY" go install github.com/minio/minio@${MINIO_VERSION}

FROM alpine:3.21.3
RUN apk add --no-cache ca-certificates wget \
    && addgroup -g 10001 -S minio \
    && adduser -u 10001 -S -G minio -H minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=build /go/bin/minio /usr/local/bin/minio
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
