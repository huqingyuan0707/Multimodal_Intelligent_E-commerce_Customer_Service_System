# 前端运行镜像：Node 构建 → Nginx 托管 dist（对应部署工程化.md §三/§八）
# 产物带 content hash 长缓存，index.html 不缓存，history 模式回退 index.html
# /api 反代地址不 bake 死：经 BACKEND_UPSTREAM 环境变量由 nginx 官方模板入口启动时渲染
# （默认 backend:8000 即 compose 服务名；单容器启动改 -e BACKEND_UPSTREAM=<host:port>，不再依赖卷挂载覆盖）
# Node 基座唯一源头是 frontend/.nvmrc（当前 22.18.0）：CI / 发版 / 本地 nvm 用它，镜像此处钉同值（exact pin，不跟 floating major）
FROM node:22.18.0-alpine AS builder
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_UPSTREAM=backend:8000
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
