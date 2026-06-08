from flask import Flask, jsonify, request
from flask_cors import CORS
import sys
from pathlib import Path
import pandas as pd
import numpy as np

backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

try:
    from fetcher import StockDataFetcher
except ImportError:
    StockDataFetcher = None

app = Flask(__name__)
CORS(app)

fetcher = StockDataFetcher() if StockDataFetcher else None

def calculate_indicators(df):
    """計算技術指標"""
    close = df['close']
    high = df['high']
    low = df['low']
    
    # MA - 移動平均線
    df['ma5'] = close.rolling(window=5).mean()
    df['ma10'] = close.rolling(window=10).mean()
    df['ma20'] = close.rolling(window=20).mean()
    df['ma60'] = close.rolling(window=60).mean() if len(df) >= 60 else None
    
    # MACD - 平滑異同移動平均線
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # RSI - 相對強弱指標
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands - 布林通道
    df['bb_middle'] = close.rolling(window=20).mean()
    bb_std = close.rolling(window=20).std()
    df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
    df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
    
    # KD - 隨機震盪指標
    low_min = low.rolling(window=9).min()
    high_max = high.rolling(window=9).max()
    rsv = 100 * ((close - low_min) / (high_max - low_min))
    df['k'] = rsv.ewm(com=2, adjust=False).mean()
    df['d'] = df['k'].ewm(com=2, adjust=False).mean()
    
    # BIAS - 乖離率
    ma6 = close.rolling(window=6).mean()
    df['bias'] = ((close - ma6) / ma6) * 100
    
    return df

@app.route("/")
def home():
    return jsonify({
        "service": "StockSense Enhanced API",
        "status": "running",
        "version": "2.0.0",
        "features": ["stock_data", "technical_indicators", "news_sentiment"],
        "endpoints": [
            "/api/health",
            "/api/stock_analysis?ticker=2330&period=1mo"
        ]
    })

@app.route("/api/health")
def health_check():
    return jsonify({"status": "healthy", "service": "stocksense_enhanced"})

@app.route("/api/stock_analysis")
def get_stock_analysis():
    ticker = request.args.get("ticker")
    period = request.args.get("period", "3mo")
    
    if not ticker:
        return jsonify({"error": "ticker required"}), 400
    
    try:
        # 獲取股價資料
        prices = fetcher.get_historical_prices(ticker, period=period, interval="1d")
        if not prices:
            return jsonify({"error": "No data"}), 404
        
        # 轉換為 DataFrame
        df = pd.DataFrame(prices)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # 計算指標
        df = calculate_indicators(df)
        
        # 準備回應資料
        result = {
            "ticker": ticker,
            "period": period,
            "data_points": len(df),
            "latest_price": float(df['close'].iloc[-1]),
            "price_change": float(df['close'].iloc[-1] - df['close'].iloc[-2]) if len(df) > 1 else 0,
            "price_data": df[['date', 'open', 'high', 'low', 'close', 'volume']].fillna(0).to_dict('records'),
            "indicators": {
                "ma": df[['date', 'ma5', 'ma10', 'ma20']].tail(20).fillna(0).to_dict('records'),
                "macd": df[['date', 'macd', 'macd_signal', 'macd_hist']].tail(20).fillna(0).to_dict('records'),
                "rsi": df[['date', 'rsi']].tail(20).fillna(0).to_dict('records'),
                "bollinger": df[['date', 'bb_upper', 'bb_middle', 'bb_lower']].tail(20).fillna(0).to_dict('records'),
                "kd": df[['date', 'k', 'd']].tail(20).fillna(0).to_dict('records'),
                "bias": df[['date', 'bias']].tail(20).fillna(0).to_dict('records')
            },
            "summary": {
                "current_rsi": float(df['rsi'].iloc[-1]) if not pd.isna(df['rsi'].iloc[-1]) else None,
                "current_k": float(df['k'].iloc[-1]) if not pd.isna(df['k'].iloc[-1]) else None,
                "current_d": float(df['d'].iloc[-1]) if not pd.isna(df['d'].iloc[-1]) else None,
                "current_bias": float(df['bias'].iloc[-1]) if not pd.isna(df['bias'].iloc[-1]) else None,
                "ma5_trend": "up" if df['close'].iloc[-1] > df['ma5'].iloc[-1] else "down",
                "macd_signal": "buy" if df['macd'].iloc[-1] > df['macd_signal'].iloc[-1] else "sell"
            }
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

handler = app
