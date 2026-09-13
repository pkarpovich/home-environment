ARG DERPER_VERSION=v1.102.4
FROM golang:1.26-alpine AS build
ARG DERPER_VERSION
RUN go install tailscale.com/cmd/derper@${DERPER_VERSION}

FROM alpine:3.22
RUN apk add --no-cache ca-certificates
COPY --from=build /go/bin/derper /usr/local/bin/derper
ENTRYPOINT ["derper"]
