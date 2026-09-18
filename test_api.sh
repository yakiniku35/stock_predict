#!/bin/bash
# 快速檢查 API 是否正常（需先執行 ./start.sh）
BASE="${BASE:-http://127.0.0.1:5000}"

echo "== /api/health =="
curl -s "$BASE/api/health" | head -c 400; echo; echo

echo "== /api/symbol_search?q=00878 =="
curl -s "$BASE/api/symbol_search?q=00878" | head -c 400; echo; echo

echo "== /api/stock_insight?ticker=0050 (ETF) =="
curl -s "$BASE/api/stock_insight?ticker=0050&period=1y&interval=1d" | head -c 400; echo; echo

echo "== /api/stock_insight?ticker=2330 (個股) =="
curl -s "$BASE/api/stock_insight?ticker=2330&period=6mo&interval=1d" | head -c 400; echo
