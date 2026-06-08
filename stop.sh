#!/bin/bash

echo "🛑 停止 StockSense 服務..."
echo ""

# 停止新聞服務
if lsof -Pi :8501 -sTCP:LISTEN -t >/dev/null ; then
    echo "⏳ 停止新聞服務 (Port 8501)..."
    lsof -ti:8501 | xargs kill -9 2>/dev/null
    echo "✅ 新聞服務已停止"
else
    echo "ℹ️  新聞服務未運行"
fi

# 停止前端服務
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "⏳ 停止前端服務 (Port 8000)..."
    lsof -ti:8000 | xargs kill -9 2>/dev/null
    echo "✅ 前端服務已停止"
else
    echo "ℹ️  前端服務未運行"
fi

echo ""
echo "✅ 所有服務已停止"
