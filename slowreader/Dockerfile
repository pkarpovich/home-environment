FROM node:26-alpine AS build
ARG SLOWREADER_REF
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 CI=1
RUN apk add --no-cache git bash && npm install -g pnpm@12.4.2
WORKDIR /src
RUN git clone --quiet https://github.com/hplush/slowreader.git . && git checkout --quiet "$SLOWREADER_REF"
RUN pnpm install --frozen-lockfile
RUN pnpm -F landings build && pnpm -F web build && pnpm -F server build

FROM node:26-alpine
WORKDIR /var/app
ENV NODE_ENV=production LOGUX_HOST=0.0.0.0 LOGUX_LOGGER=json PORT=2554
COPY --from=build /src/server/dist/ /var/app/
COPY --from=build /src/server/web/ /var/web/
RUN mkdir -p /data && chown node:node /data
USER node
EXPOSE 2554
CMD ["node", "index.ts"]
