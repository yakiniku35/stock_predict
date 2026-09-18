#!/bin/bash
# StockSense 啟動腳本：一個指令就把前端與 API 一起跑起來
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-5000}"
PYTHON_BIN="python3"
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi

echo "🚀 啟動 StockSense..."

if lsof -Pi :"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✅ 服務已在運行 (Port $PORT)"
else
    cd "$ROOT_DIR"
    PORT="$PORT" nohup "$PYTHON_BIN" backend/app.py > /tmp/stocksense_api.log 2>&1 &
    sleep 3
    echo "✅ 服務已啟動"
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
   新聞情緒：  http://127.0.0.1:$PORT/api/search?ticker=2330

🧪 執行測試：  $PYTHON_BIN tests/test_stocksense.py
🛑 停止服務：  ./stop.sh
📄 執行記錄：  /tmp/stocksense_api.log

INFO
