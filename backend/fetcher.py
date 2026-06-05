import json
import os
import pandas as pd
import yfinance as yf


class StockDataFetcher:
    """後端資料獲取模組：負責 yfinance 股價串接與組員資料整合"""

    def __init__(self, project_root=None):
        # 定義專案根目錄，方便讀取 data/ 資料夾下的新聞快照
        if project_root is None:
            self.project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..")
            )
        else:
            self.project_root = project_root

    def get_historical_prices(self, ticker: str, period="1mo", interval="1d"):
        """透過 yfinance 獲取歷史股價，並使用 pandas 進行資料清洗與結構化處理"""
        try:
            # 支援台灣市場代碼格式轉換 (例如前端輸入 2330 -> 自動轉 2330.TW)
            if ticker.isdigit() and len(ticker) == 4:
                yf_ticker = f"{ticker}.TW"
            else:
                yf_ticker = ticker

            stock = yf.Ticker(yf_ticker)
            df = stock.history(period=period, interval=interval)

            if df.empty:
                return None

            # 資料清洗 (Data Cleaning)
            df = df.reset_index()
            # 統一日期格式為 YYYY-MM-DD
            df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

            # 轉化為前端 Plotly 繪圖所需之標準欄位結構
            prices_list = []
            for _, row in df.iterrows():
                prices_list.append(
                    {
                        "date": row["Date"],
                        "open": round(row["Open"], 2),
                        "high": round(row["High"], 2),
                        "low": round(row["Low"], 2),
                        "close": round(row["Close"], 2),
                        "volume": int(row["Volume"]),
                    }
                )
            return prices_list
        except Exception as e:
            print(f"yfinance 抓取或清洗失敗: {e}")
            return None

    def get_news_sentiment_from_pipeline(self, ticker: str):
        """讀取組員邱彥嘉管線產出的情緒標註新聞資料 (對接 Phase 2/3 產出)"""
        # 對應 README 中的 Phase 2 輸出路徑
        news_file_path = os.path.join(
            self.project_root, "data", "normalized", "news_with_sentiment.jsonl"
        )

        if not os.path.exists(news_file_path):
            # 如果管線尚未執行或檔案不存在，回傳空列表，避免後端崩潰
            return []

        matched_news = []
        try:
            with open(news_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    # 篩選出符合當前查詢股票代碼的新聞
                    if str(record.get("ticker")) == str(ticker):
                        matched_news.append(
                            {
                                "id": record.get("id"),
                                "source": record.get("source"),
                                "headline": record.get("headline"),
                                "url": record.get("url"),
                                "published_at": record.get("published_at"),
                                "sentiment_score": record.get(
                                    "sentiment_score", 0.0
                                ),
                                "sentiment_label": record.get(
                                    "sentiment_label", "neutral"
                                ),
                            }
                        )
            # 依據發布時間排序，最新新聞排在前面
            matched_news.sort(
                key=lambda x: x.get("published_at", ""), reverse=True
            )
            return matched_news
        except Exception as e:
            print(f"讀取新聞情緒資料庫錯誤: {e}")
            return []