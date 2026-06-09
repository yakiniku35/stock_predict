let currentData = null;
let currentForecastHorizon = 7;

// 'multi': 可同時開啟多個副圖；'single': 互斥，只顯示一個副圖
const SUBCHART_MODE = 'multi';
const chartInteractionState = {
    activeSubcharts: new Set()
};

const API = {
    stock: '/api/stock_insight',
    news: '/api/search'
};

function isRechartsMode() {
    return !!document.getElementById('rechartsChartRoot');
}

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
            fetchStock(ticker, period, currentForecastHorizon),
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

async function fetchStock(ticker, period, forecastHorizon = 7) {
    const res = await fetch(`${API.stock}?ticker=${ticker}&period=${period}&interval=1d&forecast_horizon=${forecastHorizon}`);
    if (!res.ok) throw new Error('無法獲取股價');
    const data = await res.json();

    const prices = data.stock_price_trends;
    const indicators = data.technical_indicators || calculateIndicators(prices);
    const changeDetail = data.price_change_detail || calculatePriceChanges(prices);

    return { ...data, indicators, changeDetail };
}

async function refreshForecastHorizon(days) {
    currentForecastHorizon = days;
    if (!currentData) return;
    const ticker = currentData.ticker;
    const period = document.getElementById('period').value;
    try {
        const stockData = await fetchStock(ticker, period, currentForecastHorizon);
        currentData = { ...currentData, stockData };
        render(currentData);
    } catch (error) {
        console.error(error);
    }
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
    const volumes = prices.map(p => p.volume || 0);
    
    const sma5 = sma(closes, 5);
    const sma20 = sma(closes, 20);
    const sma60 = sma(closes, 60);
    const sma120 = sma(closes, 120);
    const sma240 = sma(closes, 240);
    
    const macd = calculateMACD(closes);
    const rsi = calculateRSI(closes, 14);
    const kd = calculateKD(highs, lows, closes, 14);
    const bb = calculateBB(closes, 20, 2);
    const bias = calculateBIAS(closes, sma20);
    const ad = calculateAD(highs, lows, closes, volumes);
    
    return {
        sma: { sma5, sma20, sma60, sma120, sma240 },
        bb,
        macd: {
            macd: macd.macdLine,
            signal: macd.signal,
            histogram: macd.histogram
        },
        kd,
        rsi,
        bias,
        ad
    };
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

function calculateBIAS(closes, ma20) {
    return closes.map((close, idx) => {
        const base = ma20[idx];
        if (base === null || base === 0) return null;
        return ((close - base) / base) * 100;
    });
}

function calculateAD(highs, lows, closes, volumes) {
    const ad = [];
    let cumulative = 0;
    for (let i = 0; i < closes.length; i++) {
        const high = highs[i];
        const low = lows[i];
        const close = closes[i];
        const volume = volumes[i] || 0;
        const range = high - low;
        const mfm = range === 0 ? 0 : (((close - low) - (high - close)) / range);
        const mfv = mfm * volume;
        cumulative += mfv;
        ad.push(cumulative);
    }
    return ad;
}

function calculatePriceChanges(prices) {
    if (!prices || prices.length === 0) {
        return {
            intraday: { change: 0, pct: 0 },
            one_day: { change: 0, pct: 0 },
            one_week: { change: 0, pct: 0 },
            one_month: { change: 0, pct: 0 }
        };
    }

    const latest = prices[prices.length - 1];
    const latestClose = latest.close;
    const latestOpen = latest.open || latestClose;
    const prevClose = prices.length >= 2 ? prices[prices.length - 2].close : null;
    const weekClose = prices.length >= 6 ? prices[prices.length - 6].close : null;
    const monthClose = prices.length >= 21 ? prices[prices.length - 21].close : null;

    const calc = (ref) => {
        if (!ref) return { change: 0, pct: 0 };
        const change = latestClose - ref;
        return {
            change,
            pct: ref === 0 ? 0 : (change / ref) * 100
        };
    };

    return {
        intraday: calc(latestOpen),
        one_day: calc(prevClose),
        one_week: calc(weekClose),
        one_month: calc(monthClose)
    };
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
    const changeDetail = stockData.changeDetail;
    
    // 更新卡片
    document.getElementById('price').textContent = latest.close.toFixed(2);
    const change = latest.close - prev.close;
    const changePercent = (change / prev.close * 100).toFixed(2);
    const priceChangeEl = document.getElementById('priceChange');
    priceChangeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)} (${changePercent}%)`;
    priceChangeEl.className = `card-change ${change >= 0 ? 'positive' : 'negative'}`;
    
    const priceDetailEl = document.getElementById('priceDetail');
    const formatChange = (item) => {
        const sign = item.change >= 0 ? '+' : '';
        const css = item.change >= 0 ? 'positive' : 'negative';
        return `<span class="${css}">${sign}${item.change.toFixed(2)} (${sign}${item.pct.toFixed(2)}%)</span>`;
    };
    priceDetailEl.innerHTML = `
        <div>日內: ${formatChange(changeDetail.intraday)}</div>
        <div>一週: ${formatChange(changeDetail.one_week)}</div>
        <div>一月: ${formatChange(changeDetail.one_month)}</div>
    `;
    
    // 情緒
    const sentiment = newsData.summary?.score_mean || 0;
    document.getElementById('sentiment').textContent = sentiment.toFixed(2);
    const sentimentTextEl = document.getElementById('sentimentText');
    const modelUsed = newsData.summary?.model_used || 'unknown';
    const modelStatus = newsData.summary?.model_status || 'unknown';
    const sentimentLabel = sentiment > 20 ? '偏正面' : sentiment < -20 ? '偏負面' : '中立';
    sentimentTextEl.textContent = `${sentimentLabel} · ${modelUsed}${modelStatus === 'ok' ? '' : ' fallback'}`;
    sentimentTextEl.title = newsData.summary?.model_error || modelStatus;
    sentimentTextEl.className = `card-change ${sentiment > 20 ? 'positive' : sentiment < -20 ? 'negative' : ''}`;
    
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
    if (isRechartsMode()) {
        if (typeof window.setRechartsSymbol === 'function') {
            window.setRechartsSymbol(ticker);
        }
    } else {
        drawMainChart(ticker, prices, stockData.indicators);
        renderSubCharts(prices, stockData.indicators);
    }
    drawIndicatorChart(ticker, prices, stockData.indicators);
    renderCompanyOverview(stockData.company_overview);
    renderModelPredictions(stockData.model_forecasts);
    renderNews(newsData.news);
}

function renderCompanyOverview(overview) {
    const el = document.getElementById('companyOverview');
    if (!el) return;
    if (!overview) {
        el.innerHTML = '<div><span class="label">無資料:</span> --</div>';
        return;
    }

    const fmtNum = (v) => (v === null || v === undefined ? '--' : Number(v).toLocaleString());
    const fmtPct = (v) => (v === null || v === undefined ? '--' : `${(Number(v) * 100).toFixed(2)}%`);

    el.innerHTML = `
        <div><span class="label">公司:</span>${overview.name || '--'}</div>
        <div><span class="label">代號:</span>${overview.symbol || '--'}</div>
        <div><span class="label">Sector:</span>${overview.sector || '--'}</div>
        <div><span class="label">Industry:</span>${overview.industry || '--'}</div>
        <div><span class="label">市值:</span>${fmtNum(overview.market_cap)}</div>
        <div><span class="label">本益比:</span>${overview.trailing_pe ?? '--'}</div>
        <div><span class="label">Forward PE:</span>${overview.forward_pe ?? '--'}</div>
        <div><span class="label">EPS:</span>${overview.eps ?? '--'}</div>
        <div><span class="label">ROE:</span>${fmtPct(overview.roe)}</div>
        <div><span class="label">Profit Margin:</span>${fmtPct(overview.profit_margin)}</div>
        <div><span class="label">Debt/Equity:</span>${overview.debt_to_equity ?? '--'}</div>
        <div><span class="label">Dividend Yield:</span>${fmtPct(overview.dividend_yield)}</div>
    `;
}

function renderModelPredictions(modelForecasts) {
    const listEl = document.getElementById('modelList');
    const statusEl = document.getElementById('trainingStatus');
    const forecastPriceEl = document.getElementById('forecastPrice');
    if (!listEl || !statusEl || !forecastPriceEl) return;

    if (!modelForecasts || !modelForecasts.predictions) {
        statusEl.innerHTML = '<span class="dot running"></span>Training...';
        forecastPriceEl.textContent = '--';
        listEl.innerHTML = '';
        return;
    }

    statusEl.innerHTML = '<span class="dot done"></span>Training Completed';
    forecastPriceEl.textContent = `Forecast Horizon ${modelForecasts.horizon_days} Days`;

    const order = ['ensemble', 'lstm', 'prophet_lite', 'gru', 'cnn_lstm', 'arima', 'ema', 'linear_regression'];
    const rows = order
        .map((key) => modelForecasts.predictions[key])
        .filter(Boolean)
        .map((item) => {
            const changeClass = item.change_pct >= 0 ? 'positive' : 'negative';
            const sign = item.change_pct >= 0 ? '+' : '';
            const best = item.model === 'Ensemble' ? 'best' : '';
            return `
                <div class="model-row ${best}">
                    <div class="model-name">${item.model}</div>
                    <div class="model-price">$${Number(item.predicted_price).toFixed(2)}</div>
                    <div class="model-change ${changeClass}">${sign}${Number(item.change_pct).toFixed(2)}%</div>
                </div>
            `;
        });
    listEl.innerHTML = rows.join('');
}

function drawMainChart(ticker, prices, indicators) {
    const dates = prices.map(p => p.date);

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

    const ma5 = { x: dates, y: indicators.sma.sma5, name: 'SMA 5', line: { color: '#0ea5e9', width: 1 } };
    const ma20 = { x: dates, y: indicators.sma.sma20, name: 'SMA 20', line: { color: '#f59e0b', width: 1 } };
    const ma60 = { x: dates, y: indicators.sma.sma60, name: 'SMA 60', line: { color: '#a78bfa', width: 1 } };
    const ma120 = { x: dates, y: indicators.sma.sma120, name: 'SMA 120', line: { color: '#22d3ee', width: 1 } };
    const ma240 = { x: dates, y: indicators.sma.sma240, name: 'SMA 240', line: { color: '#eab308', width: 1 } };

    const bbUpper = { x: dates, y: indicators.bb.upper, name: 'BB Upper', line: { color: '#94a3b8', width: 1, dash: 'dot' } };
    const bbLower = {
        x: dates,
        y: indicators.bb.lower,
        name: 'BB Lower',
        line: { color: '#94a3b8', width: 1, dash: 'dot' },
        fill: 'tonexty',
        fillcolor: 'rgba(148, 163, 184, 0.12)'
    };

    const traces = [trace, ma5, ma20, ma60, ma120, ma240, bbUpper, bbLower];
    const modelForecasts = currentData?.stockData?.model_forecasts;
    if (modelForecasts?.predictions?.ensemble) {
        const lastDate = new Date(dates[dates.length - 1]);
        const forecastDate = new Date(lastDate);
        forecastDate.setDate(forecastDate.getDate() + Number(modelForecasts.horizon_days || 7));
        traces.push({
            x: [dates[dates.length - 1], forecastDate.toISOString().split('T')[0]],
            y: [prices[prices.length - 1].close, modelForecasts.predictions.ensemble.predicted_price],
            name: `Forecast ${modelForecasts.horizon_days}D`,
            line: { color: '#f59e0b', width: 2, dash: 'dash' },
            mode: 'lines+markers'
        });
    }

    Plotly.newPlot('mainChart', traces, getLayout(), { displayModeBar: false, responsive: true });
}

function getSubchartLayout(title) {
    return {
        paper_bgcolor: '#0b1220',
        plot_bgcolor: '#020617',
        font: { color: '#94a3b8', family: 'system-ui' },
        xaxis: { gridcolor: '#1f2937', showgrid: true },
        yaxis: { gridcolor: '#1f2937', showgrid: true, side: 'right' },
        margin: { l: 40, r: 56, t: 18, b: 34 },
        height: 220,
        showlegend: true,
        legend: { x: 0, y: 1, bgcolor: 'transparent', font: { size: 10 } },
        hovermode: 'x unified',
        title: { text: title, font: { size: 12, color: '#cbd5e1' } }
    };
}

function renderSubCharts(prices, indicators) {
    const area = document.getElementById('subChartsArea');
    if (!area) return;

    const active = Array.from(chartInteractionState.activeSubcharts);
    if (active.length === 0) {
        area.style.display = 'none';
        area.innerHTML = '';
        return;
    }

    area.style.display = 'grid';
    area.innerHTML = active.map((name) => {
        const titleMap = {
            macd: 'MACD',
            rsi: 'RSI',
            kd: 'KD',
            bias: 'BIAS',
            ad: 'AD'
        };
        return `
            <div class="subchart-item">
                <div class="subchart-title">${titleMap[name] || name.toUpperCase()}</div>
                <div id="subchart-${name}" style="height: 220px;"></div>
            </div>
        `;
    }).join('');

    active.forEach((name) => {
        drawSubChart(name, prices, indicators);
    });
}

function drawSubChart(type, prices, indicators) {
    const targetId = `subchart-${type}`;
    const dates = prices.map(p => p.date);

    if (type === 'macd') {
        const macdLine = { x: dates, y: indicators.macd.macd, name: 'MACD', line: { color: '#0ea5e9' } };
        const signal = { x: dates, y: indicators.macd.signal, name: 'Signal', line: { color: '#f59e0b' } };
        const hist = {
            x: dates,
            y: indicators.macd.histogram,
            name: 'Histogram',
            type: 'bar',
            marker: { color: indicators.macd.histogram.map(v => v >= 0 ? '#10b981' : '#ef4444') }
        };
        Plotly.newPlot(targetId, [hist, macdLine, signal], getSubchartLayout('MACD'), { displayModeBar: false, responsive: true });
        return;
    }

    if (type === 'rsi') {
        const rsiTrace = { x: dates, y: indicators.rsi, name: 'RSI', line: { color: '#a855f7' } };
        const upper = { x: dates, y: Array(dates.length).fill(70), name: '70', line: { color: '#ef4444', dash: 'dash', width: 1 } };
        const lower = { x: dates, y: Array(dates.length).fill(30), name: '30', line: { color: '#10b981', dash: 'dash', width: 1 } };
        Plotly.newPlot(targetId, [rsiTrace, upper, lower], getSubchartLayout('RSI'), { displayModeBar: false, responsive: true });
        return;
    }

    if (type === 'kd') {
        const kTrace = { x: dates, y: indicators.kd.k, name: 'K', line: { color: '#facc15' } };
        const dTrace = { x: dates, y: indicators.kd.d, name: 'D', line: { color: '#a855f7' } };
        Plotly.newPlot(targetId, [kTrace, dTrace], getSubchartLayout('KD'), { displayModeBar: false, responsive: true });
        return;
    }

    if (type === 'bias') {
        const biasTrace = { x: dates, y: indicators.bias, name: 'BIAS 20', line: { color: '#f97316' } };
        const zeroLine = { x: dates, y: Array(dates.length).fill(0), name: '0%', line: { color: '#64748b', dash: 'dash', width: 1 } };
        Plotly.newPlot(targetId, [biasTrace, zeroLine], getSubchartLayout('BIAS'), { displayModeBar: false, responsive: true });
        return;
    }

    if (type === 'ad') {
        const adMillion = indicators.ad.map(v => (v === null ? null : v / 1000000));
        const adTrace = { x: dates, y: adMillion, name: 'A/D (M)', line: { color: '#22c55e' } };
        Plotly.newPlot(targetId, [adTrace], getSubchartLayout('AD'), { displayModeBar: false, responsive: true });
    }
}

function toggleSubchart(indicator) {
    if (SUBCHART_MODE === 'single') {
        if (chartInteractionState.activeSubcharts.has(indicator) && chartInteractionState.activeSubcharts.size === 1) {
            chartInteractionState.activeSubcharts.clear();
        } else {
            chartInteractionState.activeSubcharts.clear();
            chartInteractionState.activeSubcharts.add(indicator);
        }
    } else {
        if (chartInteractionState.activeSubcharts.has(indicator)) {
            chartInteractionState.activeSubcharts.delete(indicator);
        } else {
            chartInteractionState.activeSubcharts.add(indicator);
        }
    }

    updateSubchartToggleStyles();

    if (currentData) {
        const prices = currentData.stockData.stock_price_trends;
        const indicators = currentData.stockData.indicators;
        renderSubCharts(prices, indicators);
    }
}

function updateSubchartToggleStyles() {
    const buttons = document.querySelectorAll('[data-subchart]');
    buttons.forEach((btn) => {
        const key = btn.getAttribute('data-subchart');
        if (!key) return;
        btn.classList.toggle('active', chartInteractionState.activeSubcharts.has(key));
    });
}

function drawIndicatorChart(ticker, prices, indicators) {
    const latestClose = prices[prices.length - 1]?.close || 0;
    const ref = (offset) => {
        const idx = prices.length - 1 - offset;
        return idx >= 0 ? prices[idx].close : latestClose;
    };
    const labels = ['日內', '1日', '1週', '1月'];
    const refs = [prices[prices.length - 1]?.open || latestClose, ref(1), ref(5), ref(20)];
    const values = refs.map(v => (latestClose - v) / (v || 1) * 100);

    const heatBar = {
        x: labels,
        y: values,
        type: 'bar',
        name: '漲跌幅(%)',
        marker: {
            color: values,
            colorscale: [
                [0, '#ef4444'],
                [0.5, '#64748b'],
                [1, '#10b981']
            ],
            cmin: -8,
            cmax: 8,
            showscale: false
        }
    };

    Plotly.newPlot('indChart', [heatBar], getLayout(true), { displayModeBar: false, responsive: true });
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

function showLoading(show) {
    document.getElementById('loading').classList.toggle('active', show);
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('StockSense loaded');
    document.getElementById('ticker').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') analyze();
    });

    const initialTicker = document.getElementById('ticker')?.value?.trim()?.toUpperCase();
    if (initialTicker && isRechartsMode() && typeof window.setRechartsSymbol === 'function') {
        window.setRechartsSymbol(initialTicker);
    }

    const subchartButtons = document.querySelectorAll('[data-subchart]');
    subchartButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const indicator = btn.getAttribute('data-subchart');
            if (!indicator) return;
            toggleSubchart(indicator);
        });
    });

    updateSubchartToggleStyles();

    const horizonTabs = document.getElementById('horizonTabs');
    if (horizonTabs) {
        horizonTabs.addEventListener('click', async (e) => {
            const target = e.target;
            if (!(target instanceof HTMLElement)) return;
            if (!target.classList.contains('horizon-tab')) return;
            const days = Number(target.dataset.days || '7');
            document.querySelectorAll('.horizon-tab').forEach((tab) => tab.classList.remove('active'));
            target.classList.add('active');
            await refreshForecastHorizon(days);
        });
    }
});
