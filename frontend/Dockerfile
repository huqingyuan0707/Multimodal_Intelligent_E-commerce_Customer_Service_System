# 前端运行镜像：Node 构建 → Nginx 托管 dist（对应部署工程化.md §三/§八）
# 产物带 content hash 长缓存，index.html 不缓存，history 模式回退 index.html
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
