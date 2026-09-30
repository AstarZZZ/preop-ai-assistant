FROM python:3.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PREOP_MODELS_ROOT=/models PREOP_ASR_DEVICE=cpu
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
WORKDIR /service
RUN sed -i 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-asr.txt ./
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements-asr.txt
COPY asr_service.py ./
RUN mkdir -p /models
EXPOSE 8766
HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=8 CMD python -c "import urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=4)); raise SystemExit(0 if d.get('state') == 'ready' else 1)"
CMD ["python", "-m", "uvicorn", "asr_service:app", "--host", "0.0.0.0", "--port", "8766"]
