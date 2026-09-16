# 后端运行镜像：依赖层与运行层分离，非 root 运行（对应部署工程化.md §三）
# 双钉死（ADR-0002 不可变精神）：基镜像 tag+digest；依赖走 requirements.lock 精确闭包（dev 工具不进镜像）
FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS base
WORKDIR /srv/app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
 && pip check

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
RUN useradd -m appuser
WORKDIR /srv/app
COPY --from=base /usr/local /usr/local
COPY app ./app
# RAG 种子与迁移脚本随镜像走：容器内 knowledge.json 缺失则检索恒空（恒 2001），
# 缺 alembic 则 client_msg_id 等新增列升不上去（新代码读旧库直接炸表结构）
COPY seed ./seed
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
# SQLite 落盘目录预建并授权（命名卷默认 root 属主，appuser 否则写不进库）
RUN mkdir -p /srv/app/data && chown appuser:appuser /srv/app/data
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
