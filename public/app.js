// API Configuration
const API = {
    stock: 'https://stock-predict-azure.vercel.app/api/stock_insight',
    news: 'http://127.0.0.1:8501/api/search'
};

// State
let currentData = null;

// Event Handlers
async function handleSearch(event) {
    event.preventDefault();
    
    const ticker = document.getElementById('ticker').value.trim().toUpperCase();
    const period = document.getElementById('period').value;
    const maxNews = document.getElementById('maxNews').value;
    
    if (!ticker) return;
    
    showLoading(true);
    
    try {
        const [stockData, newsData] = await Promise.all([
            fetchStockData(ticker, period),
            fetchNewsData(ticker, maxNews)
        ]);
        
        currentData = { ticker, stockData, newsData };
        renderDashboard(currentData);
        
    } catch (error) {
        showError(error.message);
    } finally {
        showLoading(false);
    }
}

// API Calls
async function fetchStockData(ticker, period) {
    const response = await fetch(`${API.stock}?ticker=${ticker}&period=${period}&interval=1d`);
    if (!response.ok) throw new Error('無法獲取股價資料');
    return await response.json();
}

async function fetchNewsData(ticker, maxNews) {
    try {
        const response = await fetch(`${API.news}?ticker=${ticker}&query=${ticker}&max_articles=${maxNews}`);
        if (!response.ok) throw new Error('新聞服務未啟動');
        return await response.json();
    } catch (error) {
        console.warn('News API unavailable:', error);
        return {
            ok: true,
            summary: { records: 0, score_mean: 0, positive_ratio: 0, neutral_ratio: 0, negative_ratio: 0 },
            news: []
        };
    }
}

// Render Functions
function renderDashboard({ ticker, stockData, newsData }) {
    updateStats(stockData, newsData);
    renderPriceChart(ticker, stockData.stock_price_trends);
    renderSentimentChart(newsData.summary);
    renderNewsFeed(newsData.news);
}

function updateStats(stockData, newsData) {
    document.getElementById('statsGrid').style.display = 'grid';
    
    const prices = stockData.stock_price_trends || [];
    const latestPrice = prices[prices.length - 1]?.close;
    const previousPrice = prices[prices.length - 2]?.close;
    const priceChange = latestPrice && previousPrice ? 
        ((latestPrice - previousPrice) / previousPrice * 100).toFixed(2) : null;
    
    const avgSentiment = newsData.summary?.score_mean || 0;
    
    document.getElementById('latestPrice').textContent = 
        latestPrice ? latestPrice.toFixed(2) : '--';
    
    const priceChangeEl = document.getElementById('priceChange');
    if (priceChange) {
        priceChangeEl.textContent = `${priceChange > 0 ? '+' : ''}${priceChange}%`;
        priceChangeEl.className = `stat-change ${priceChange > 0 ? 'positive' : 'negative'}`;
    }
    
    document.getElementById('newsCount').textContent = newsData.summary?.records || 0;
    document.getElementById('avgSentiment').textContent = avgSentiment.toFixed(2);
    document.getElementById('dataPoints').textContent = prices.length;
    
    const sentimentTrendEl = document.getElementById('sentimentTrend');
    sentimentTrendEl.textContent = avgSentiment > 0 ? '偏正面' : avgSentiment < 0 ? '偏負面' : '中立';
    sentimentTrendEl.className = `stat-change ${avgSentiment > 0 ? 'positive' : avgSentiment < 0 ? 'negative' : ''}`;
    
    const { positive_ratio = 0, neutral_ratio = 0, negative_ratio = 0 } = newsData.summary || {};
    document.getElementById('positivePercent').textContent = `${(positive_ratio * 100).toFixed(0)}%`;
    document.getElementById('neutralPercent').textContent = `${(neutral_ratio * 100).toFixed(0)}%`;
    document.getElementById('negativePercent').textContent = `${(negative_ratio * 100).toFixed(0)}%`;
}

function renderPriceChart(ticker, prices) {
    const dates = prices.map(p => p.date);
    const closes = prices.map(p => p.close);
    const opens = prices.map(p => p.open);
    const highs = prices.map(p => p.high);
    const lows = prices.map(p => p.low);
    
    const trace = {
        x: dates,
        close: closes,
        high: highs,
        low: lows,
        open: opens,
        type: 'candlestick',
        name: ticker,
        increasing: { line: { color: '#10b981' } },
        decreasing: { line: { color: '#ef4444' } }
    };
    
    const layout = {
        paper_bgcolor: '#1a2332',
        plot_bgcolor: '#141b2d',
        font: { color: '#94a3b8', family: 'Inter' },
        xaxis: {
            gridcolor: '#2d3748',
            showgrid: true,
            zeroline: false
        },
        yaxis: {
            gridcolor: '#2d3748',
            showgrid: true,
            zeroline: false,
            side: 'right'
        },
        margin: { l: 40, r: 60, t: 20, b: 40 },
        height: 400,
        showlegend: false,
        hovermode: 'x unified'
    };
    
    const config = {
        displayModeBar: false,
        responsive: true
    };
    
    Plotly.newPlot('priceChart', [trace], layout, config);
}

function renderSentimentChart(summary) {
    const { positive_ratio = 0, neutral_ratio = 0, negative_ratio = 0 } = summary || {};
    
    const data = [{
        values: [positive_ratio, neutral_ratio, negative_ratio],
        labels: ['正面', '中立', '負面'],
        type: 'pie',
        hole: 0.5,
        marker: {
            colors: ['#10b981', '#94a3b8', '#ef4444']
        },
        textinfo: 'label+percent',
        textfont: { color: '#e2e8f0', size: 12 },
        hovertemplate: '%{label}: %{percent}<extra></extra>'
    }];
    
    const layout = {
        paper_bgcolor: '#1a2332',
        plot_bgcolor: '#141b2d',
        font: { color: '#94a3b8', family: 'Inter' },
        height: 300,
        margin: { l: 20, r: 20, t: 20, b: 20 },
        showlegend: false
    };
    
    const config = {
        displayModeBar: false,
        responsive: true
    };
    
    Plotly.newPlot('sentimentChart', data, layout, config);
}

function renderNewsFeed(news) {
    const feed = document.getElementById('newsFeed');
    
    if (!news || news.length === 0) {
        feed.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <div class="empty-title">暫無新聞</div>
                <div class="empty-text">請確認本地服務已啟動</div>
            </div>
        `;
        return;
    }
    
    feed.innerHTML = news.map(item => {
        const sentiment = getSentiment(item.sentiment_label, item.sentiment_score);
        const date = new Date(item.published_at).toLocaleDateString('zh-TW');
        
        return `
            <div class="news-item" onclick="window.open('${item.url}', '_blank')">
                <div class="news-header">
                    <div class="news-title">
                        <a href="${item.url}" target="_blank" rel="noopener">${item.headline}</a>
                    </div>
                    <span class="sentiment-badge ${sentiment.class}">${sentiment.label}</span>
                </div>
                <div class="news-meta">
                    <span class="news-source">${item.source}</span>
                    <span>•</span>
                    <span>${date}</span>
                </div>
            </div>
        `;
    }).join('');
}

function getSentiment(label, score) {
    if (label === 'positive' || score > 0.1) {
        return { label: '正面', class: 'positive' };
    } else if (label === 'negative' || score < -0.1) {
        return { label: '負面', class: 'negative' };
    }
    return { label: '中立', class: 'neutral' };
}

// UI Helpers
function showLoading(show) {
    const overlay = document.getElementById('loadingOverlay');
    overlay.classList.toggle('active', show);
}

function showError(message) {
    alert(message);
    console.error(message);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log('StockSense Dashboard initialized');
    console.log('Stock API:', API.stock);
    console.log('News API:', API.news);
});
