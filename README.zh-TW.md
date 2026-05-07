# 股票預測

[English README](README.md)

台股與美股走勢預測專案。目標是結合歷史行情、財務指標、新聞與社群情緒訊號，協助進行價格趨勢分析與視覺化呈現。

> 專案狀態：早期骨架。目前 repository 主要包含文件與依賴檔案占位，尚未加入實際應用程式碼。

## 功能

- 使用 [yfinance](https://github.com/ranaroussi/yfinance) 取得歷史股價與財務指標。
- 透過爬蟲蒐集新聞、社群討論等輔助市場資訊。
- 使用 RNN 類模型分析情緒訊號。
- 整合價格、指標與情緒特徵，預測股票價格走勢方向。
- 使用 [Plotly](https://github.com/plotly/plotly.py) 呈現互動式圖表與分析結果。

## 快速開始

複製專案：

```bash
git clone https://github.com/yakiniku35/stock_predict.git
cd stock_predict
```

建立並啟用虛擬環境：

```bash
python -m venv .venv
.venv\Scripts\activate
```

安裝依賴：

```bash
pip install -r requirements.txt
```

目前尚未提供後端與前端的啟動入口。待 `backend/`、`frontend/` 等模組加入後，請同步更新本段落的啟動指令。

## 專案架構

目前結構：

```text
stock_predict/
├── README.md
├── README.zh-TW.md
├── LICENSE
├── requirements.txt
└── .gitignore
```

預計結構：

```text
stock_predict/
├── backend/          # API、資料處理、模型推論
├── frontend/         # Plotly/Dash 或網頁介面
├── data/             # 本機資料集與快取行情資料
├── models/           # 訓練腳本與模型檔案
├── crawlers/         # 新聞與社群資料蒐集器
├── tests/            # 單元測試與整合測試
└── requirements.txt
```

## 資料來源

- 歷史 K 線與財務指標：[yfinance](https://github.com/ranaroussi/yfinance)
- 輔助市場資訊：透過爬蟲蒐集的新聞、社群討論與其他公開來源

蒐集或重新散布資料前，請先確認各資料來源的服務條款與使用限制。

## 分工與貢獻者

感謝所有貢獻者。

[![](https://contrib.rocks/image?repo=yakiniku35/stock_predict)](https://github.com/yakiniku35/stock_predict/graphs/contributors)

## 開發筆記

- 依賴套件或啟動入口變更時，請同步更新 README 的安裝與執行步驟。
- API key、token 等敏感資訊請放在本機環境變數或被忽略的 `.env` 檔案中。
- 除非有明確版本控管需求，請避免提交原始資料集、模型 checkpoint 或快取檔。
- 核心資料處理、模型與 API 模組加入後，建議同步補上測試。

## 免責聲明

本專案僅供研究與學習用途，不構成任何投資建議、財務建議或保證性預測結果。
