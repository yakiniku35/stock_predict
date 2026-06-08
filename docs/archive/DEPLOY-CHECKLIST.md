# ✅ Vercel 部署檢查清單

## 📋 部署前檢查

- [x] 已建立 `vercel.json` 配置檔
- [x] 已建立 `api/index.py` Serverless Function
- [x] 已建立 `.vercelignore` 忽略檔案
- [x] 已更新 `requirements.txt` 依賴清單
- [x] 已驗證所有 Python 檔案語法
- [x] 已建立 `package.json`

## �� 立即部署

### 選項 1: 使用 Vercel CLI (推薦)

```bash
# 1. 安裝 Vercel CLI (如果尚未安裝)
npm install -g vercel

# 2. 登入 Vercel
vercel login

# 3. 進入專案目錄
cd /Users/peterchiu/stock_predict

# 4. 首次部署（測試環境）
vercel

# 5. 部署到生產環境
vercel --prod
```

### 選項 2: 使用 GitHub 整合

```bash
# 1. 提交所有變更
git add .
git commit -m "配置 Vercel 部署"
git push origin main

# 2. 前往 Vercel Dashboard
# https://vercel.com/new

# 3. 選擇專案
# Import Git Repository > 選擇 stock_predict

# 4. 配置設定（自動偵測）
# Framework Preset: Other
# Build Command: (留空)
# Output Directory: (留空)

# 5. 點擊 Deploy
```

## 🌐 部署後測試

```bash
# 替換 YOUR-PROJECT 為你的 Vercel 專案網址

# 測試首頁
curl https://YOUR-PROJECT.vercel.app/

# 測試健康檢查
curl https://YOUR-PROJECT.vercel.app/api/health

# 測試股票 API
curl "https://YOUR-PROJECT.vercel.app/api/stock_insight?ticker=2330&period=1mo&interval=1d"
```

## 📁 已準備的檔案

```
stock_predict/
├── api/
│   └── index.py              ✅ Serverless Function
├── backend/
│   ├── app.py               ✅ 後端邏輯
│   └── fetcher.py           ✅ 資料獲取
├── vercel.json              ✅ Vercel 配置
├── requirements.txt         ✅ Python 依賴
├── .vercelignore           ✅ 忽略檔案
├── package.json            ✅ NPM 配置
└── README-VERCEL.md        ✅ 部署指南
```

## ⚙️ Vercel 配置詳情

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

### API 端點
- `GET /` - 服務資訊
- `GET /api/health` - 健康檢查
- `GET /api/stock_insight` - 股票資料查詢

### 查詢參數
- `ticker` (必填) - 股票代碼 (例: 2330, AAPL)
- `period` (可選) - 時間範圍 (預設: 1mo)
- `interval` (可選) - 時間間隔 (預設: 1d)

## 🔒 環境變數（如需要）

在 Vercel Dashboard > Settings > Environment Variables 添加：

```
# 目前不需要環境變數
# 未來如需 API Key 或資料庫連線，在此添加
```

## 📊 監控建議

1. **查看部署日誌**
   ```bash
   vercel logs
   ```

2. **監控效能**
   - 前往 Vercel Dashboard > Analytics
   - 查看請求數、錯誤率、響應時間

3. **設定告警**
   - 在 Vercel Dashboard > Settings > Notifications
   - 啟用部署失敗通知

## 🐛 疑難排解

### 部署失敗
```bash
# 查看詳細日誌
vercel logs --follow

# 本地測試
vercel dev
```

### API 錯誤
- 檢查 `api/index.py` 語法
- 確認 `requirements.txt` 包含所有依賴
- 查看 Vercel Dashboard 的 Functions 日誌

### 超時問題
- Vercel Hobby 限制 10 秒
- 優化程式碼或升級方案

## 🎉 部署完成後

1. ✅ 測試所有 API 端點
2. ✅ 更新 README 添加 Vercel URL
3. ✅ 設定自訂網域（可選）
4. ✅ 監控部署狀態

---

💡 **下一步**: 查看 `README-VERCEL.md` 了解更多優化建議
