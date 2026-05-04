# 股票預測

[English README](README.md)

台股/美股走勢預測工具。以 [yfinance](https://github.com/ranaroussi/yfinance) 取得歷史資料、搭配爬蟲輔助新聞資訊，使用 RNN 情緒分析搭配預測價格趨勢，並透過 [plotly](https://github.com/plotly/plotly.py) 介面呈現結果

## 功能


# Quick Start

```bash
git clone https://github.com/yakiniku35/stock_predict.git
cd stock_predict
pip install -r requirements.txt
```

啟動後端：

```bash
python backend/app.py
```

啟動前端（另開終端）：

```bash
python frontend/app.py
```

開啟 `http://localhost:8050`


## 專案架構


## 資料來源

- 歷史 K 線與財務指標：yfinance
- 輔助資料（新聞、社群討論等）：爬蟲

# 分工

- 後端 API 與 yfinance 串接 — @Devotioe
- 爬蟲腳本 — @yakiniku35
- 前端 UI、Plotly 圖表、整合測試 — @組員C

## 開發筆記

