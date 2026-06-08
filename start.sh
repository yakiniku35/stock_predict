#!/bin/bash

echo "🚀 啟動 StockSense..."
echo ""

# 檢查是否已有服務在運行
if lsof -Pi :8501 -sTCP:LISTEN -t >/dev/null ; then
    echo "✅ 新聞服務已在運行 (Port 8501)"
else
    echo "⏳ 啟動新聞服務..."
    cd frontend
    nohup python3 dashboard.py > /tmp/stocksense_news.log 2>&1 &
    cd ..
    sleep 3
    echo "✅ 新聞服務已啟動"
fi

if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null ; then
    echo "✅ 前端服務已在運行 (Port 8000)"
else
    echo "⏳ 啟動前端服務..."
    cd public
    nohup python3 -m http.server 8000 > /tmp/stocksense_web.log 2>&1 &
    cd ..
    sleep 2
    echo "✅ 前端服務已啟動"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "🎉 StockSense 已啟動！"
echo "═══════════════════════════════════════════════════"
echo ""
echo "📱 訪問方式："
echo ""
echo "  專業儀表板:  http://localhost:8000/dashboard.html"
echo "  測試頁面:    http://localhost:8000/demo.html"
echo "  原生服務:    http://127.0.0.1:8501"
echo ""
echo "📊 API 端點："
echo ""
echo "  新聞分析:    http://127.0.0.1:8501/api/search?ticker=2330"
echo "  股價查詢:    https://stock-predict-azure.vercel.app/api/stock_insight?ticker=2330"
echo ""
echo "🛑 停止服務："
echo ""
echo "  執行: ./stop.sh"
echo ""
echo "═══════════════════════════════════════════════════"
