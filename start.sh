#!/bin/bash
# StockSense 啟動腳本：一個指令就把前端與 API 一起跑起來
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-5000}"
PID_FILE="$ROOT_DIR/.stocksense.pid"
LOG_FILE="${LOG_FILE:-/tmp/stocksense_api.log}"

PYTHON_BIN="python3"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

echo "🚀 啟動 StockSense..."

# 只認自己寫下的 PID，不去掃整個連接埠（避免誤殺別人的服務）
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "✅ 服務已在運行 (PID $(cat "$PID_FILE"), Port $PORT)"
else
    rm -f "$PID_FILE"
    cd "$ROOT_DIR"
    PORT="$PORT" nohup "$PYTHON_BIN" backend/app.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "✅ 服務已啟動 (PID $(cat "$PID_FILE"))"
    else
        rm -f "$PID_FILE"
        echo "❌ 啟動失敗，請查看 $LOG_FILE" >&2
        tail -n 20 "$LOG_FILE" >&2 || true
        exit 1
    fi
fi

cat <<INFO

═══════════════════════════════════════════════════
🎉 StockSense 已啟動
═══════════════════════════════════════════════════

📱 網頁介面：  http://127.0.0.1:$PORT/

📊 API 端點：
   健康檢查：  http://127.0.0.1:$PORT/api/health
   代號搜尋：  http://127.0.0.1:$PORT/api/symbol_search?q=0050
   完整分析：  http://127.0.0.1:$PORT/api/stock_insight?ticker=0050&period=1y&interval=1d
   多檔比較：  http://127.0.0.1:$PORT/api/compare?tickers=0050,006208,00878
   新聞情緒：  http://127.0.0.1:$PORT/api/search?ticker=2330

🧪 執行測試：  $PYTHON_BIN tests/test_stocksense.py
🛑 停止服務：  ./stop.sh
📄 執行記錄：  $LOG_FILE

INFO
