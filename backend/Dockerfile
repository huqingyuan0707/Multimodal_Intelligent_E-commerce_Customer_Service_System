# 后端运行镜像：依赖层与运行层分离，非 root 运行（对应部署工程化.md §三）
FROM python:3.11-slim AS base
WORKDIR /srv/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
RUN useradd -m appuser
WORKDIR /srv/app
COPY --from=base /usr/local /usr/local
COPY app ./app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
