#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RUN_DIR="$PROJECT_DIR/run"
LOG_DIR="$PROJECT_DIR/logs"
ASR_PYTHON="$PROJECT_DIR/.venv-asr/bin/python"
LLM_MODEL=${PREOP_LLM_MODEL:-qwen3:4b}
mkdir -p "$RUN_DIR" "$LOG_DIR"

if [ ! -x "$ASR_PYTHON" ]; then
  echo "缺少 .venv-asr，请先按 README 安装 requirements-asr.txt"
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "缺少 FFmpeg，请先安装音频解码环境"
  exit 1
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo "缺少 Ollama，请先安装本地大模型运行时"
  exit 1
fi

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
  echo $! >"$RUN_DIR/ollama.pid"
fi

OLLAMA_READY=0
for _attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then OLLAMA_READY=1; break; fi
  sleep 1
done
if [ "$OLLAMA_READY" -ne 1 ]; then
  echo "Ollama 启动超时，请查看 logs/ollama.log"
  exit 1
fi
if ! ollama show "$LLM_MODEL" >/dev/null 2>&1; then
  echo "未找到 $LLM_MODEL，请先执行：ollama pull $LLM_MODEL"
  exit 1
fi

if ! curl -fsS http://127.0.0.1:8766/health >/dev/null 2>&1; then
  cd "$PROJECT_DIR"
  nohup "$ASR_PYTHON" -m uvicorn asr_service:app --host 127.0.0.1 --port 8766 >"$LOG_DIR/asr.log" 2>&1 &
  echo $! >"$RUN_DIR/asr.pid"
fi

ASR_READY=0
for _attempt in $(seq 1 90); do
  ASR_STATE=$(curl -fsS http://127.0.0.1:8766/health 2>/dev/null || true)
  case "$ASR_STATE" in *'"state":"ready"'*) ASR_READY=1; break;; esac
  sleep 1
done
if [ "$ASR_READY" -ne 1 ]; then
  echo "ASR 模型启动超时，请查看 logs/asr.log"
  exit 1
fi

cd "$PROJECT_DIR"
export PREOP_ASR_BACKEND=remote
export PREOP_ASR_URL=http://127.0.0.1:8766
export PREOP_LLM_URL=http://127.0.0.1:11434/v1
export PREOP_LLM_MODEL="$LLM_MODEL"
exec python3 app.py
