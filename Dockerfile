FROM node:20-bookworm-slim AS frontend-build
WORKDIR /build
COPY package.json package-lock.json vite.config.js ./
COPY frontend ./frontend
RUN npm ci && npm run build

FROM python:3.10-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PREOP_HOST=0.0.0.0 PREOP_PORT=8765
WORKDIR /app
COPY app.py db.py services.py prompts.py ./
COPY 东阳市人民医院logo.png 杭州电子科技大学logo.png ./
COPY --from=frontend-build /build/static ./static
RUN mkdir -p /app/data/uploads
EXPOSE 8765
HEALTHCHECK --interval=20s --timeout=4s --start-period=15s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"
CMD ["python", "app.py"]
