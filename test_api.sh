#!/bin/bash

# 測試本地 API (啟動 backend/app.py 後執行)
echo "🧪 測試本地 API..."
echo ""

echo "1️⃣ 測試健康檢查..."
curl -s http://localhost:5000/api/health | python3 -m json.tool
echo ""

echo "2️⃣ 測試股票查詢 (2330)..."
curl -s "http://localhost:5000/api/stock_insight?ticker=2330&period=1mo&interval=1d" | python3 -m json.tool | head -30
echo ""

echo "✅ 測試完成！"
