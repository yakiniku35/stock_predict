let currentData = null;
let currentChart = 'price';

const API = {
    stock: '/api/stock_insight',
    news: '/api/search'
};

async function analyze() {
    const ticker = document.getElementById('ticker').value.trim().toUpperCase();
    const period = document.getElementById('period').value;
    const btn = document.getElementById('btn');
    
    if (!ticker) return;
    
    btn.disabled = true;
    btn.textContent = '分析中...';
    showLoading(true);
    
    try {
        const [stockData, newsData] = await Promise.all([
            fetchStock(ticker, period),
            fetchNews(ticker, 50)
        ]);
        
        currentData = { ticker, stockData, newsData };
        render(currentData);
        
    } catch (error) {
        alert('錯誤: ' + error.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '分析';
        showLoading(false);
    }
}

async function fetchStock(ticker, period) {
    const res = await fetch(`${API.stock}?ticker=${ticker}&period=${period}&interval=1d`);
    if (!res.ok) throw new Error('無法獲取股價');
    const data = await res.json();
    
    // 計算指標
    const prices = data.stock_price_trends;
    const indicators = calculateIndicators(prices);
    
    return { ...data, indicators };
}

async function fetchNews(ticker, max) {
    try {
        const res = await fetch(`${API.news}?ticker=${encodeURIComponent(ticker)}&max_articles=${max}&model_type=rnn`);
        if (!res.ok) throw new Error('新聞服務未啟動');
        return await res.json();
    } catch (e) {
        console.warn('News unavailable:', e);
        return { summary: { records: 0, score_mean: 0, model_used: 'none', model_status: 'unavailable' }, news: [] };
    }
}

function calculateIndicators(prices) {
    const closes = prices.map(p => p.close);
    const highs = prices.map(p => p.high);
    const lows = prices.map(p => p.low);
    
    // MA
    const ma5 = sma(closes, 5);
    const ma10 = sma(closes, 10);
    const ma20 = sma(closes, 20);
    
    // MACD
    const macd = calculateMACD(closes);
    
    // RSI
    const rsi = calculateRSI(closes, 14);
    
    // KD
    const kd = calculateKD(highs, lows, closes, 9);
    
    // Bollinger Bands
    const bb = calculateBB(closes, 20, 2);
    
    return { ma5, ma10, ma20, macd, rsi, kd, bb };
}

function sma(data, period) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            result.push(null);
        } else {
            const sum = data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0);
            result.push(sum / period);
        }
    }
    return result;
}

function ema(data, period) {
    const k = 2 / (period + 1);
    const result = [data[0]];
    for (let i = 1; i < data.length; i++) {
        result.push(data[i] * k + result[i - 1] * (1 - k));
    }
    return result;
}

function calculateMACD(closes) {
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const macdLine = ema12.map((v, i) => v - ema26[i]);
    const signal = ema(macdLine, 9);
    const histogram = macdLine.map((v, i) => v - signal[i]);
    return { macdLine, signal, histogram };
}

function calculateRSI(closes, period) {
    const changes = closes.slice(1).map((v, i) => v - closes[i]);
    const gains = changes.map(v => v > 0 ? v : 0);
    const losses = changes.map(v => v < 0 ? -v : 0);
    
    const avgGain = sma(gains, period);
    const avgLoss = sma(losses, period);
    
    const rsi = avgGain.map((gain, i) => {
        if (avgLoss[i] === 0) return 100;
        const rs = gain / avgLoss[i];
        return 100 - (100 / (1 + rs));
    });
    
    return [null, ...rsi];
}

function calculateKD(highs, lows, closes, period) {
    const rsv = [];
    for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) {
            rsv.push(null);
        } else {
            const periodHighs = highs.slice(i - period + 1, i + 1);
            const periodLows = lows.slice(i - period + 1, i + 1);
            const highMax = Math.max(...periodHighs);
            const lowMin = Math.min(...periodLows);
            rsv.push(((closes[i] - lowMin) / (highMax - lowMin)) * 100);
        }
    }
    
    const k = ema(rsv.filter(v => v !== null), 3);
    const d = ema(k, 3);
    
    const kFull = rsv.map((v, i) => {
        const idx = rsv.slice(0, i + 1).filter(x => x !== null).length - 1;
        return idx >= 0 ? k[idx] : null;
    });
    
    const dFull = rsv.map((v, i) => {
        const idx = rsv.slice(0, i + 1).filter(x => x !== null).length - 1;
        return idx >= 0 ? d[idx] : null;
    });
    
    return { k: kFull, d: dFull };
}

function calculateBB(closes, period, stdDev) {
    const middle = sma(closes, period);
    const upper = [];
    const lower = [];
    
    for (let i = 0; i < closes.length; i++) {
        if (i < period - 1) {
            upper.push(null);
            lower.push(null);
        } else {
            const slice = closes.slice(i - period + 1, i + 1);
            const mean = middle[i];
            const variance = slice.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / period;
            const std = Math.sqrt(variance);
            upper.push(mean + std * stdDev);
            lower.push(mean - std * stdDev);
        }
    }
    
    return { upper, middle, lower };
}

function render({ ticker, stockData, newsData }) {
    const prices = stockData.stock_price_trends;
    const latest = prices[prices.length - 1];
    const prev = prices[prices.length - 2];
    
    // 更新卡片
    document.getElementById('price').textContent = latest.close.toFixed(2);
    const change = latest.close - prev.close;
    const changePercent = (change / prev.close * 100).toFixed(2);
    const priceChangeEl = document.getElementById('priceChange');
    priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePercent}%)`;
    priceChangeEl.className = `card-change ${change >= 0 ? 'positive' : 'negative'}`;
    
    // 情緒
    const sentiment = newsData.summary?.score_mean || 0;
    document.getElementById('sentiment').textContent = sentiment.toFixed(2);
    const sentimentTextEl = document.getElementById('sentimentText');
    const modelUsed = newsData.summary?.model_used || 'unknown';
    const modelStatus = newsData.summary?.model_status || 'unknown';
    const sentimentLabel = sentiment > 0.1 ? '偏正面' : sentiment < -0.1 ? '偏負面' : '中立';
    sentimentTextEl.textContent = `${sentimentLabel} · ${modelUsed}${modelStatus === 'ok' ? '' : ' fallback'}`;
    sentimentTextEl.title = newsData.summary?.model_error || modelStatus;
    sentimentTextEl.className = `card-change ${sentiment > 0.1 ? 'positive' : sentiment < -0.1 ? 'negative' : ''}`;
    
    // RSI
    const rsi = stockData.indicators.rsi;
    const latestRSI = rsi[rsi.length - 1];
    document.getElementById('rsi').textContent = latestRSI ? latestRSI.toFixed(1) : '--';
    const rsiTextEl = document.getElementById('rsiText');
    if (latestRSI) {
        rsiTextEl.textContent = latestRSI > 70 ? '超買' : latestRSI < 30 ? '超賣' : '正常';
        rsiTextEl.className = `card-change ${latestRSI > 70 ? 'negative' : latestRSI < 30 ? 'positive' : ''}`;
    }
    
    // 繪製圖表
    drawMainChart(ticker, prices, stockData.indicators);
    drawIndicatorChart(ticker, prices, stockData.indicators);
    renderNews(newsData.news);
}

function drawMainChart(ticker, prices, indicators) {
    const dates = prices.map(p => p.date);
    
    if (currentChart === 'price') {
        const trace = {
            x: dates,
            close: prices.map(p => p.close),
            high: prices.map(p => p.high),
            low: prices.map(p => p.low),
            open: prices.map(p => p.open),
            type: 'candlestick',
            name: ticker,
            increasing: { line: { color: '#10b981' } },
            decreasing: { line: { color: '#ef4444' } }
        };
        
        const ma5 = { x: dates, y: indicators.ma5, name: 'MA5', line: { color: '#0ea5e9', width: 1 } };
        const ma20 = { x: dates, y: indicators.ma20, name: 'MA20', line: { color: '#f59e0b', width: 1 } };
        
        Plotly.newPlot('mainChart', [trace, ma5, ma20], getLayout(), { displayModeBar: false, responsive: true });
        
    } else if (currentChart === 'macd') {
        const macdLine = { x: dates, y: indicators.macd.macdLine, name: 'MACD', line: { color: '#0ea5e9' } };
        const signal = { x: dates, y: indicators.macd.signal, name: 'Signal', line: { color: '#f59e0b' } };
        const hist = {
            x: dates,
            y: indicators.macd.histogram,
            name: 'Histogram',
            type: 'bar',
            marker: { color: indicators.macd.histogram.map(v => v >= 0 ? '#10b981' : '#ef4444') }
        };
        
        Plotly.newPlot('mainChart', [hist, macdLine, signal], getLayout(), { displayModeBar: false, responsive: true });
        
    } else if (currentChart === 'rsi') {
        const rsiTrace = { x: dates, y: indicators.rsi, name: 'RSI', line: { color: '#0ea5e9' } };
        const upper = { x: dates, y: Array(dates.length).fill(70), name: '超買', line: { color: '#ef4444', dash: 'dash', width: 1 } };
        const lower = { x: dates, y: Array(dates.length).fill(30), name: '超賣', line: { color: '#10b981', dash: 'dash', width: 1 } };
        
        Plotly.newPlot('mainChart', [rsiTrace, upper, lower], getLayout(), { displayModeBar: false, responsive: true });
        
    } else if (currentChart === 'kd') {
        const kTrace = { x: dates, y: indicators.kd.k, name: 'K', line: { color: '#0ea5e9' } };
        const dTrace = { x: dates, y: indicators.kd.d, name: 'D', line: { color: '#f59e0b' } };
        
        Plotly.newPlot('mainChart', [kTrace, dTrace], getLayout(), { displayModeBar: false, responsive: true });
    }
}

function drawIndicatorChart(ticker, prices, indicators) {
    const dates = prices.map(p => p.date);
    
    const upper = { x: dates, y: indicators.bb.upper, name: '上軌', line: { color: '#888', width: 1 } };
    const middle = { x: dates, y: indicators.bb.middle, name: '中軌', line: { color: '#0ea5e9', width: 1 } };
    const lower = { x: dates, y: indicators.bb.lower, name: '下軌', line: { color: '#888', width: 1 } };
    const price = { x: dates, y: prices.map(p => p.close), name: '收盤價', line: { color: '#fff', width: 2 } };
    
    Plotly.newPlot('indChart', [upper, middle, lower, price], getLayout(true), { displayModeBar: false, responsive: true });
}

function getLayout(small = false) {
    return {
        paper_bgcolor: '#111',
        plot_bgcolor: '#000',
        font: { color: '#888', family: 'system-ui' },
        xaxis: { gridcolor: '#222', showgrid: true },
        yaxis: { gridcolor: '#222', showgrid: true, side: 'right' },
        margin: { l: 40, r: 60, t: small ? 10 : 20, b: 40 },
        height: small ? 300 : 400,
        showlegend: true,
        legend: { x: 0, y: 1, bgcolor: 'transparent' },
        hovermode: 'x unified'
    };
}

function renderNews(news) {
    const list = document.getElementById('newsList');
    
    if (!news || news.length === 0) {
        list.innerHTML = '<div style="padding: 2rem; text-align: center; color: #888;">無新聞資料</div>';
        return;
    }
    
    list.innerHTML = news.slice(0, 10).map(item => {
        const sentiment = item.sentiment_label;
        const badgeClass = sentiment === 'positive' ? 'pos' : sentiment === 'negative' ? 'neg' : 'neu';
        const badgeText = sentiment === 'positive' ? '正面' : sentiment === 'negative' ? '負面' : '中立';
        const modelText = item.sentiment_model === 'rnn' ? 'RNN' : 'Lexicon';
        
        return `
            <div class="news-item" onclick="window.open('${item.url}', '_blank')">
                <div class="news-title">${item.headline}</div>
                <div class="news-meta">
                    <span>${item.source}</span>
                    <span class="badge ${badgeClass}">${badgeText}</span>
                    <span>${modelText}</span>
                </div>
            </div>
        `;
    }).join('');
}

function switchChart(type) {
    currentChart = type;
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    event.target.classList.add('active');
    
    if (currentData) {
        drawMainChart(currentData.ticker, currentData.stockData.stock_price_trends, currentData.stockData.indicators);
    }
}

function showLoading(show) {
    document.getElementById('loading').classList.toggle('active', show);
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('StockSense loaded');
    document.getElementById('ticker').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyze();
    });
});
