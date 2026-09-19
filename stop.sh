#!/bin/bash
# 停止 StockSense 服務（只停 start.sh 自己啟動的那個行程）
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT_DIR/.stocksense.pid"

echo "🛑 停止 StockSense 服務..."

if [ ! -f "$PID_FILE" ]; then
    echo "ℹ️  找不到 $PID_FILE，服務可能未透過 ./start.sh 啟動"
    echo "    若要手動確認：lsof -Pi :\${PORT:-5000} -sTCP:LISTEN"
    exit 0
fi

PID="$(cat "$PID_FILE")"

if ! kill -0 "$PID" 2>/dev/null; then
    echo "ℹ️  PID $PID 已不存在，清除 PID 檔"
    rm -f "$PID_FILE"
    exit 0
fi

# 確認這個 PID 真的是我們的服務，避免 PID 被系統重複配置後誤殺
if ! tr '\0' ' ' < "/proc/$PID/cmdline" 2>/dev/null | grep -q "backend/app.py"; then
    echo "⚠️  PID $PID 看起來不是 StockSense（cmdline 不符），不予停止" >&2
    echo "    請手動確認後刪除 $PID_FILE" >&2
    exit 1
fi

kill "$PID" 2>/dev/null
for _ in $(seq 1 20); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.25
done

if kill -0 "$PID" 2>/dev/null; then
    echo "⏳ 仍在運行，改送 SIGKILL"
    kill -9 "$PID" 2>/dev/null
fi

rm -f "$PID_FILE"
echo "✅ 已停止 (PID $PID)"
