# The build output is static files, so build on the native platform even when
# targeting arm64; only the nginx stage needs to match the target architecture.
FROM --platform=$BUILDPLATFORM node:24.15-alpine3.22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.2-alpine
# The image's entrypoint renders /etc/nginx/templates/*.template with envsubst.
ENV API_UPSTREAM=http://api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
