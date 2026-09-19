#!/bin/bash
# 快速檢查 API 是否正常（需先執行 ./start.sh）
# 任何端點回傳 4xx / 5xx 或連線失敗都會讓這支腳本以非 0 結束
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:5000}"

request() {
    local label="$1" url="$2" body
    echo "== $label =="
    if ! body="$(curl --fail --silent --show-error --max-time 30 "$url")"; then
        echo "❌ 請求失敗: $url" >&2
        return 1
    fi
    printf '%.400s\n\n' "$body"
}

request "/api/health" "$BASE/api/health"
request "/api/symbol_search?q=00878" "$BASE/api/symbol_search?q=00878"
request "/api/stock_insight?ticker=0050 (ETF)" "$BASE/api/stock_insight?ticker=0050&period=1y&interval=1d"
request "/api/stock_insight?ticker=2330 (個股)" "$BASE/api/stock_insight?ticker=2330&period=6mo&interval=1d"
request "/api/compare (多檔比較)" "$BASE/api/compare?tickers=0050,006208&period=1y"

echo "✅ 所有端點都回傳 2xx"
