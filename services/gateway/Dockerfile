# --- build stage -------------------------------------------------------------
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/gateway ./cmd/gateway \
 && CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/migrate ./cmd/migrate \
 && CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/seed   ./cmd/seed

# --- runtime stage ------------------------------------------------------------
FROM alpine:3.20
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 wakili
COPY --from=build /out/ /app/
USER wakili
EXPOSE 8080
ENTRYPOINT ["/app/gateway"]
