#!/bin/bash
# 停止 StockSense 服務
echo "🛑 停止 StockSense 服務..."

for PORT in "${PORT:-5000}" 8000 8501; do
    if lsof -Pi :"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
        lsof -ti:"$PORT" | xargs kill -9 2>/dev/null
        echo "✅ 已停止 Port $PORT 的服務"
    fi
done

echo "✅ 完成"
