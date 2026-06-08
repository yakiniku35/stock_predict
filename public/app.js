let priceChart = null;

// API 端點配置
const API_CONFIG = {
    // Vercel 部署的股價 API
    STOCK_API: 'https://stock-predict-azure.vercel.app/api/stock_insight',
    // 本地的新聞情緒分析 API（需要啟動 frontend/dashboard.py）
    NEWS_API: 'http://127.0.0.1:8501/api/search'
};

async function searchStock(event) {
    event.preventDefault();

    const ticker = document.getElementById('ticker').value.trim().toUpperCase();
    const period = document.getElementById('period').value;
    const maxArticles = document.getElementById('maxArticles').value;
    const searchBtn = document.getElementById('searchBtn');

    if (!ticker) return;

    searchBtn.disabled = true;
    searchBtn.textContent = '⏳ 分析中...';
    showLoading();

    try {
        // 1. 獲取股價資料（Vercel API）
        const priceData = await fetchStockPrice(ticker, period);
        
        // 2. 獲取新聞和情緒分析（本地 API）
        const newsData = await fetchNewsAndSentiment(ticker, maxArticles);

        // 3. 顯示結果
        displayResults(ticker, priceData, newsData);

    } catch (error) {
        showError(error.message);
        console.error('Error:', error);
    } finally {
        searchBtn.disabled = false;
        searchBtn.textContent = '🔍 分析';
    }
}

async function fetchStockPrice(ticker, period) {
    try {
        const response = await fetch(
            `${API_CONFIG.STOCK_API}?ticker=${ticker}&period=${period}&interval=1d`
        );
        
        if (!response.ok) {
            throw new Error('無法獲取股價資料');
        }

        return await response.json();
    } catch (error) {
        throw new Error(`股價 API 錯誤: ${error.message}`);
    }
}

async function fetchNewsAndSentiment(ticker, maxArticles) {
    try {
        const response = await fetch(
            `${API_CONFIG.NEWS_API}?ticker=${ticker}&query=${ticker}&max_articles=${maxArticles}`
        );

        if (!response.ok) {
            throw new Error('無法獲取新聞資料，請確認本地服務已啟動（python frontend/dashboard.py）');
        }

        return await response.json();
    } catch (error) {
        // 如果本地 API 無法連線，返回空資料但不影響股價顯示
        console.warn('News API not available:', error.message);
        return {
            ok: true,
            summary: {
                records: 0,
                score_mean: 0,
                positive_ratio: 0,
                neutral_ratio: 0,
                negative_ratio: 0
            },
            news: []
        };
    }
}

function displayResults(ticker, priceData, newsData) {
    document.getElementById('statsGrid').style.display = 'grid';
    document.getElementById('sentimentCard').style.display = 'block';

    // 更新統計數據
    const newsCount = newsData.summary?.records || 0;
    const avgScore = newsData.summary?.score_mean || 0;
    const pricePoints = priceData.stock_price_trends?.length || 0;
    const latestPrice = priceData.stock_price_trends?.[pricePoints - 1]?.close || '--';

    document.getElementById('newsCount').textContent = newsCount;
    document.getElementById('avgSentiment').textContent = avgScore.toFixed(2);
    document.getElementById('pricePoints').textContent = pricePoints;
    document.getElementById('latestPrice').textContent = 
        typeof latestPrice === 'number' ? latestPrice.toFixed(2) : latestPrice;

    // 更新情緒百分比
    const positiveRatio = newsData.summary?.positive_ratio || 0;
    const neutralRatio = newsData.summary?.neutral_ratio || 0;
    const negativeRatio = newsData.summary?.negative_ratio || 0;

    document.getElementById('positivePercent').textContent = (positiveRatio * 100).toFixed(0) + '%';
    document.getElementById('neutralPercent').textContent = (neutralRatio * 100).toFixed(0) + '%';
    document.getElementById('negativePercent').textContent = (negativeRatio * 100).toFixed(0) + '%';

    // 繪製股價圖表
    drawPriceChart(priceData.stock_price_trends, ticker);

    // 顯示新聞列表
    displayNews(newsData.news || []);
}

function drawPriceChart(priceData, ticker) {
    const ctx = document.getElementById('priceChart').getContext('2d');

    if (priceChart) {
        priceChart.destroy();
    }

    const labels = priceData.map(d => d.date);
    const prices = priceData.map(d => d.close);

    priceChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: `${ticker} 收盤價`,
                data: prices,
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 3,
                pointHoverRadius: 5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { 
                        color: '#e2e8f0',
                        font: { size: 14 }
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    borderColor: '#6366f1',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    ticks: { 
                        color: '#94a3b8',
                        maxRotation: 45,
                        minRotation: 45
                    },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                },
                y: {
                    ticks: { 
                        color: '#94a3b8',
                        callback: function(value) {
                            return value.toFixed(2);
                        }
                    },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                }
            }
        }
    });
}

function displayNews(news) {
    const newsList = document.getElementById('newsList');

    if (news.length === 0) {
        newsList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📭</div>
                <p>沒有找到相關新聞</p>
                <p style="font-size: 0.875rem; margin-top: 0.5rem;">請確認本地服務已啟動</p>
            </div>
        `;
        return;
    }

    newsList.innerHTML = news.map(item => {
        const sentiment = getSentimentLabel(item.sentiment_label, item.sentiment_score);
        const date = formatDate(item.published_at);

        return `
            <div class="news-item">
                <div class="news-title">
                    <a href="${item.url}" target="_blank" rel="noopener noreferrer">
                        ${item.headline}
                    </a>
                </div>
                <div class="news-meta">
                    <span>${item.source} • ${date}</span>
                    <span class="sentiment-badge ${sentiment.class}">${sentiment.label}</span>
                </div>
            </div>
        `;
    }).join('');
}

function getSentimentLabel(label, score) {
    if (label === 'positive' || score > 0.1) {
        return { label: '正面', class: 'positive' };
    } else if (label === 'negative' || score < -0.1) {
        return { label: '負面', class: 'negative' };
    } else {
        return { label: '中立', class: 'neutral' };
    }
}

function formatDate(dateString) {
    if (!dateString) return '未知';
    
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString('zh-TW', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
    } catch (e) {
        return dateString;
    }
}

function showLoading() {
    document.getElementById('newsList').innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>正在分析資料...</p>
            <p style="font-size: 0.875rem; margin-top: 0.5rem; color: #64748b;">
                股價資料來自 Vercel API<br>
                新聞資料來自本地服務
            </p>
        </div>
    `;
}

function showError(message) {
    const newsList = document.getElementById('newsList');
    newsList.innerHTML = `
        <div class="error">
            <strong>❌ 錯誤</strong>
            <p style="margin-top: 0.5rem;">${message}</p>
        </div>
        <div class="empty-state">
            <p style="font-size: 0.875rem;">
                <strong>疑難排解：</strong><br>
                1. 確認股票代碼正確<br>
                2. 確認本地服務已啟動：<br>
                <code style="background: rgba(0,0,0,0.3); padding: 0.25rem 0.5rem; border-radius: 4px;">
                    cd frontend && python dashboard.py
                </code>
            </p>
        </div>
    `;
}

// 頁面載入時的說明
window.addEventListener('DOMContentLoaded', () => {
    console.log('StockSense Dashboard Loaded');
    console.log('Stock API:', API_CONFIG.STOCK_API);
    console.log('News API:', API_CONFIG.NEWS_API);
    console.log('');
    console.log('使用方式：');
    console.log('1. 輸入股票代碼（例如：2330, AAPL）');
    console.log('2. 選擇時間範圍和新聞數量');
    console.log('3. 點擊「分析」按鈕');
    console.log('');
    console.log('注意：新聞情緒分析需要啟動本地服務');
    console.log('執行：cd frontend && python dashboard.py');
});
