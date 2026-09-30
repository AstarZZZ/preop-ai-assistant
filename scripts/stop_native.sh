#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for SERVICE in asr ollama; do
  PID_FILE="$PROJECT_DIR/run/$SERVICE.pid"
  if [ -f "$PID_FILE" ]; then
    PID=$(sed -n '1p' "$PID_FILE")
    case "$PID" in *[!0-9]*|'') ;; *) kill "$PID" 2>/dev/null || true;; esac
    rm -f "$PID_FILE"
  fi
done
echo "已停止本项目启动的模型服务"
