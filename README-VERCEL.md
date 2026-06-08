# 🚀 Vercel 部署指南

## 📋 前置準備

### 1. 安裝 Vercel CLI
```bash
npm install -g vercel
```

### 2. 登入 Vercel
```bash
vercel login
```

## 🛠️ 部署步驟

### 方式一：使用 Vercel CLI

```bash
cd /Users/peterchiu/stock_predict

# 首次部署
vercel

# 生產環境部署
vercel --prod
```

### 方式二：使用 GitHub 整合

1. **推送到 GitHub**
```bash
git add .
git commit -m "準備部署到 Vercel"
git push origin main
```

2. **連接 Vercel**
- 前往 https://vercel.com/new
- 選擇你的 GitHub 專案
- Vercel 會自動偵測 `vercel.json` 配置
- 點擊 "Deploy"

## 📁 專案結構（Vercel）

```
stock_predict/
├── api/                    # Vercel Serverless Functions
│   └── index.py           # 主要 API 端點
├── backend/               # 後端邏輯
│   ├── app.py
│   └── fetcher.py
├── vercel.json            # Vercel 配置
├── requirements.txt       # Python 依賴
└── .vercelignore         # 忽略檔案
```

## 🔧 Vercel 配置說明

### vercel.json
```json
{
  "version": 2,
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
```

### 環境變數
Vercel 部署不需要額外環境變數，所有依賴都在 `requirements.txt` 中。

## 🌐 API 端點

部署後，你的 API 會在以下端點可用：

- **首頁**: `https://your-project.vercel.app/`
- **健康檢查**: `https://your-project.vercel.app/api/health`
- **股票資料**: `https://your-project.vercel.app/api/stock_insight?ticker=2330&period=1mo&interval=1d`

## 📝 測試部署

```bash
# 測試健康檢查
curl https://your-project.vercel.app/api/health

# 測試股票 API
curl "https://your-project.vercel.app/api/stock_insight?ticker=2330&period=1mo&interval=1d"
```

## ⚠️ 重要限制

### Vercel Serverless 限制
- **執行時間**: 最多 10 秒（Hobby 方案）/ 60 秒（Pro 方案）
- **檔案大小**: Lambda 函數最大 50MB
- **冷啟動**: 第一次請求可能較慢

### 功能限制
由於 Vercel 是 serverless 環境：
- ❌ 無法執行長時間爬蟲（建議改用排程服務）
- ❌ 無法儲存本地檔案（需使用資料庫或雲端儲存）
- ✅ 只提供股票價格 API
- ✅ 輕量級即時查詢

## 🎯 建議架構

### 後端 API (Vercel)
- 股票價格查詢
- 基本財務資料
- API 健康檢查

### 前端儀表板 (另外部署)
- 選項 1: Vercel（靜態頁面 + API 呼叫）
- 選項 2: Netlify
- 選項 3: GitHub Pages

### 爬蟲與分析 (定時任務)
- 選項 1: GitHub Actions
- 選項 2: 本地執行 + 資料庫
- 選項 3: Google Cloud Functions

## 🔄 更新部署

```bash
# 修改程式碼後重新部署
git add .
git commit -m "更新功能"
git push origin main

# 或使用 Vercel CLI
vercel --prod
```

## 🐛 常見問題

### Q: 部署失敗怎麼辦？
A: 檢查 Vercel 部署日誌：
```bash
vercel logs
```

### Q: API 超時怎麼辦？
A: Vercel Hobby 方案限制 10 秒，考慮：
1. 優化查詢邏輯
2. 使用快取
3. 升級到 Pro 方案

### Q: 如何使用自訂網域？
A: 在 Vercel Dashboard > Settings > Domains 添加

## 📊 監控與日誌

```bash
# 查看部署狀態
vercel ls

# 查看日誌
vercel logs [deployment-url]

# 查看專案資訊
vercel inspect [deployment-url]
```

## 💡 優化建議

1. **啟用快取**
```python
from flask import make_response

@app.route("/api/stock_insight")
def get_stock_insight():
    response = make_response(jsonify(data))
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
```

2. **使用 CDN**
- Vercel 自動提供全球 CDN

3. **限流保護**
```python
from functools import wraps
from time import time

def rate_limit(max_per_minute=60):
    # 實作限流邏輯
    pass
```

## 🎉 完成！

部署完成後，你的 API 就可以在全球範圍內使用了！

---

📖 Vercel 文件: https://vercel.com/docs
🔧 Python 部署指南: https://vercel.com/docs/concepts/functions/serverless-functions/runtimes/python
