# PatchLoop backend (Go/Gin). Multi-stage: static binary on a small Alpine base.
FROM golang:1.27-alpine AS build
WORKDIR /src
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -trimpath -ldflags="-s -w" -o /out/patchloop-api ./cmd/api

FROM alpine:3.20
# CA roots from the build stage (no package download needed at this stage).
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
RUN adduser -D -u 10001 app
USER app
COPY --from=build /out/patchloop-api /usr/local/bin/patchloop-api
ENV PORT=8080 GIN_MODE=release
EXPOSE 8080
CMD ["patchloop-api"]
