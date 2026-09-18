/* =============================================================================
 * StockSense 前端主程式
 * - 單一 API 呼叫（/api/stock_insight）就取回價格、指標、預測、判讀與新聞
 * - 主題（自動 / 淺色 / 深色）切換後，Plotly 圖表會跟著換色
 * ========================================================================== */

'use strict';

const API = {
    insight: '/api/stock_insight',
    symbolSearch: '/api/symbol_search',
    compare: '/api/compare',
    health: '/api/health',
};

const STORAGE = {
    theme: 'stocksense.theme',
    ticker: 'stocksense.ticker',
    prefs: 'stocksense.prefs',
    watchlist: 'stocksense.watchlist',
};

const DCA_UNIT = 1000;   // 後端用單位金額試算，前端按比例換算

const state = {
    ticker: '0050',
    period: '1y',
    interval: '1d',
    horizon: 7,
    overlays: new Set(),
    subcharts: new Set(),
    data: null,
    loading: false,
    suggestions: [],
    highlighted: -1,
    actionTab: 'dividends',
    watchlist: [],
    compareList: [],
    compareData: null,
    dcaAmount: 5000,
};

/* ----------------------------- 小工具 ----------------------------- */
const $ = (id) => document.getElementById(id);
const el = (selector, root = document) => root.querySelector(selector);
const els = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function safeStorage(action, key, value) {
    try {
        if (action === 'get') return localStorage.getItem(key);
        if (action === 'set') return localStorage.setItem(key, value);
    } catch (error) {
        return null; // 無痕模式或被封鎖時靜默略過
    }
    return null;
}

function debounce(fn, wait) {
    let timer = null;
    return (...args) => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => fn(...args), wait);
    };
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
}

const isNum = (value) => typeof value === 'number' && Number.isFinite(value);

function fmtPrice(value, digits = 2) {
    if (!isNum(Number(value))) return '--';
    return Number(value).toLocaleString('zh-TW', {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
}

function fmtSigned(value, digits = 2, suffix = '') {
    if (!isNum(Number(value))) return '--';
    const num = Number(value);
    return `${num >= 0 ? '+' : ''}${num.toFixed(digits)}${suffix}`;
}

function fmtSignedAmount(value, digits = 0) {
    const num = Number(value);
    if (!isNum(num)) return '--';
    return num.toLocaleString('zh-TW', {
        signDisplay: 'exceptZero',
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function fmtCompact(value) {
    if (value === null || value === undefined || value === '') return '--';
    const num = Number(value);
    if (!isNum(num)) return '--';
    return new Intl.NumberFormat('zh-TW', { notation: 'compact', maximumFractionDigits: 2 }).format(num);
}

function fmtPercentFromRatio(value, digits = 2) {
    const num = Number(value);
    if (!isNum(num)) return '--';
    // yfinance 的殖利率有時是 0.0325、有時是 3.25，這裡統一判斷
    const percent = Math.abs(num) <= 1 ? num * 100 : num;
    return `${percent.toFixed(digits)}%`;
}

function fmtRelativeTime(iso) {
    if (!iso) return '';
    const time = new Date(iso).getTime();
    if (Number.isNaN(time)) return '';
    const diffMinutes = Math.round((time - Date.now()) / 60000);
    const formatter = new Intl.RelativeTimeFormat('zh-TW', { numeric: 'auto' });
    const absolute = Math.abs(diffMinutes);
    if (absolute < 60) return formatter.format(diffMinutes, 'minute');
    if (absolute < 60 * 24) return formatter.format(Math.round(diffMinutes / 60), 'hour');
    return formatter.format(Math.round(diffMinutes / 1440), 'day');
}

function changeClass(value) {
    const num = Number(value);
    if (!isNum(num) || num === 0) return '';
    return num > 0 ? 'up' : 'down';
}

function toast(message, type = 'error', timeout = 6000) {
    const stack = $('toastStack');
    if (!stack) return;
    const node = document.createElement('div');
    node.className = 'toast';
    node.dataset.type = type;
    node.innerHTML = `<span style="flex:1">${escapeHtml(message)}</span>
        <button class="toast-close" type="button" aria-label="關閉">×</button>`;
    el('.toast-close', node).addEventListener('click', () => node.remove());
    stack.appendChild(node);
    window.setTimeout(() => node.remove(), timeout);
}

function setLoading(loading) {
    state.loading = loading;
    document.body.classList.toggle('is-loading', loading);
    const button = $('analyzeBtn');
    if (button) button.disabled = loading;
}

function setApiState(status, text) {
    const node = $('apiState');
    if (!node) return;
    node.dataset.state = status;
    $('apiStateText').textContent = text;
}

/* ----------------------------- 主題 ----------------------------- */
const themeMedia = window.matchMedia('(prefers-color-scheme: dark)');

function resolveTheme(choice) {
    if (choice === 'dark' || choice === 'light') return choice;
    return themeMedia.matches ? 'dark' : 'light';
}

function applyTheme(choice, { redraw = true } = {}) {
    const resolved = resolveTheme(choice);
    document.documentElement.dataset.theme = resolved;
    safeStorage('set', STORAGE.theme, choice);

    els('[data-theme-choice]').forEach((button) => {
        button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice));
    });

    document.body.classList.add('is-switching-theme');
    window.setTimeout(() => document.body.classList.remove('is-switching-theme'), 300);

    if (redraw && state.data) renderCharts();
}

function initTheme() {
    const choice = safeStorage('get', STORAGE.theme) || 'auto';
    applyTheme(choice, { redraw: false });

    els('[data-theme-choice]').forEach((button) => {
        button.addEventListener('click', () => applyTheme(button.dataset.themeChoice));
    });

    themeMedia.addEventListener('change', () => {
        const current = safeStorage('get', STORAGE.theme) || 'auto';
        if (current === 'auto') applyTheme('auto');
    });
}

function cssVar(name, fallback = '#888') {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value || '').trim() || fallback;
}

function chartTheme() {
    return {
        text: cssVar('--text-muted', '#94a3b8'),
        grid: cssVar('--grid', 'rgba(148,163,184,0.15)'),
        up: cssVar('--up', '#34d399'),
        down: cssVar('--down', '#fb7185'),
        accent: cssVar('--accent', '#38bdf8'),
        warn: cssVar('--warn', '#fbbf24'),
        info: cssVar('--info', '#a78bfa'),
        surface: cssVar('--surface-solid', '#111827'),
    };
}

/* ----------------------------- 偏好設定 ----------------------------- */
function savePrefs() {
    safeStorage('set', STORAGE.prefs, JSON.stringify({
        period: state.period,
        interval: state.interval,
        horizon: state.horizon,
        overlays: Array.from(state.overlays),
        subcharts: Array.from(state.subcharts),
        dcaAmount: state.dcaAmount,
    }));
    safeStorage('set', STORAGE.ticker, state.ticker);
}

function loadPrefs() {
    const savedTicker = safeStorage('get', STORAGE.ticker);
    if (savedTicker) state.ticker = savedTicker;

    try {
        const prefs = JSON.parse(safeStorage('get', STORAGE.prefs) || '{}');
        if (prefs.period) state.period = prefs.period;
        if (prefs.interval) state.interval = prefs.interval;
        if (prefs.horizon) state.horizon = Number(prefs.horizon);
        if (Array.isArray(prefs.overlays)) state.overlays = new Set(prefs.overlays);
        if (Array.isArray(prefs.subcharts)) state.subcharts = new Set(prefs.subcharts);
        if (prefs.dcaAmount) state.dcaAmount = Number(prefs.dcaAmount);
    } catch (error) {
        /* 忽略毀損的設定 */
    }
}

function syncControls() {
    $('tickerInput').value = state.ticker;
    els('[data-period]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.period === state.period)));
    els('[data-interval]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.interval === state.interval)));
    els('[data-horizon]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.horizon) === state.horizon)));
    $('dcaAmount').value = String(state.dcaAmount);
    els('[data-overlay]').forEach((b) => b.setAttribute('aria-pressed', String(state.overlays.has(b.dataset.overlay))));
    els('[data-subchart]').forEach((b) => b.setAttribute('aria-pressed', String(state.subcharts.has(b.dataset.subchart))));
}

/* ----------------------------- 自動完成 ----------------------------- */
async function fetchSuggestions(query) {
    try {
        const response = await fetch(`${API.symbolSearch}?q=${encodeURIComponent(query)}&limit=8`);
        if (!response.ok) return [];
        const data = await response.json();
        return data.results || [];
    } catch (error) {
        return [];
    }
}

function renderSuggestions(items) {
    const list = $('comboList');
    state.suggestions = items;
    state.highlighted = -1;

    if (!items.length) {
        list.innerHTML = '<div class="combo-empty">找不到符合的標的，可直接輸入代號查詢</div>';
    } else {
        list.innerHTML = items.map((item, index) => `
            <div class="combo-option" role="option" id="combo-option-${index}" data-code="${escapeHtml(item.code)}" aria-selected="false">
                <span class="code">${escapeHtml(item.code)}</span>
                <span class="name">${escapeHtml(item.name_zh)} · ${escapeHtml(item.name_en)}</span>
                <span class="tag" data-kind="${escapeHtml(item.kind)}">${item.kind === 'etf' ? 'ETF' : item.kind === 'index' ? '指數' : '股票'}</span>
            </div>`).join('');

        els('.combo-option', list).forEach((option) => {
            option.addEventListener('mousedown', (event) => {
                event.preventDefault();
                selectSuggestion(option.dataset.code);
            });
        });
    }
    openCombo(true);
}

function openCombo(open) {
    const list = $('comboList');
    list.dataset.open = String(open);
    $('tickerInput').setAttribute('aria-expanded', String(open));
    if (!open) state.highlighted = -1;
}

function highlightSuggestion(offset) {
    const options = els('.combo-option');
    if (!options.length) return;
    state.highlighted = (state.highlighted + offset + options.length) % options.length;
    options.forEach((option, index) => {
        const active = index === state.highlighted;
        option.setAttribute('aria-selected', String(active));
        if (active) option.scrollIntoView({ block: 'nearest' });
    });
}

function selectSuggestion(code) {
    if (!code) return;
    $('tickerInput').value = code;
    state.ticker = code;
    openCombo(false);
    analyze();
}

/* ----------------------------- 主流程 ----------------------------- */
async function analyze() {
    const input = $('tickerInput').value.trim();
    if (!input) {
        toast('請先輸入股票或 ETF 代號', 'info');
        return;
    }
    state.ticker = input;
    savePrefs();
    setLoading(true);
    setApiState('idle', '查詢中…');

    const query = new URLSearchParams({
        ticker: input,
        period: state.period,
        interval: state.interval,
        forecast_horizon: String(state.horizon),
        include_news: '1',
    });

    try {
        const response = await fetch(`${API.insight}?${query}`);
        const data = await response.json();

        if (!response.ok || data.status !== 'success') {
            setApiState('error', '查詢失敗');
            const suggestions = (data.suggestions || []).map((item) => item.code).join('、');
            toast(`${data.message || '查詢失敗'}${suggestions ? `｜你是不是要找：${suggestions}` : ''}`);
            return;
        }

        state.data = data;
        setApiState('ok', `已更新 ${new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`);
        render();
        syncUrl();
        updateWatchButton();

        const code = data.symbol?.display_code || state.ticker;
        if (!state.compareList.length) {
            state.compareList = [code];
            renderCompareChips();
        }
    } catch (error) {
        setApiState('error', '連線失敗');
        toast(`無法連線到分析服務：${error.message}`);
    } finally {
        setLoading(false);
    }
}

function render() {
    const data = state.data;
    if (!data) return;
    renderHeader(data);
    renderMetrics(data);
    renderMarketRead(data.market_read);
    renderCharts();
    renderForecast(data.forecast);
    renderOverview(data.company_overview, data.symbol);
    renderCorporateActions(data.corporate_actions, data.company_overview);
    renderExtraPanel(data);
    renderRisk(data.risk_metrics, data.symbol);
    renderDca(data.dca, data.company_overview);
    renderNews(data.news, data.news_summary);
}

function renderHeader(data) {
    const symbol = data.symbol || {};
    const name = symbol.name_zh || symbol.name || symbol.display_code;
    const periodText = data.request?.effective_period || state.period;
    $('chartTitle').textContent = `${name}（${symbol.display_code || state.ticker}）走勢`;
    $('chartSubtitle').textContent =
        `資料來源 ${symbol.resolved} · 範圍 ${periodText} · 週期 ${state.interval} · 共 ${data.metrics?.total_fetched_prices ?? 0} 筆`;

    if (data.request?.effective_period && data.request.effective_period !== data.request.period) {
        toast(`所選週期（${state.interval}）最多只能查 ${data.request.effective_period}，已自動調整範圍`, 'info', 4500);
    }
}

function renderMetrics(data) {
    const prices = data.stock_price_trends || [];
    const latest = prices[prices.length - 1];
    const detail = data.price_change_detail || {};
    const currency = data.company_overview?.currency || '';

    if (latest) {
        $('metricPrice').textContent = `${fmtPrice(latest.close)}`;
        const oneDay = detail.one_day || { change: 0, pct: 0 };
        const changeEl = $('metricPriceChange');
        changeEl.className = `metric-sub ${changeClass(oneDay.change)}`;
        changeEl.textContent = `${fmtSigned(oneDay.change)} (${fmtSigned(oneDay.pct, 2, '%')}) · ${currency}`;
        $('metricPriceDetail').innerHTML = [
            ['一週', detail.one_week],
            ['一月', detail.one_month],
            ['三月', detail.three_month],
        ].map(([label, item]) => item
            ? `<span>${label} <b class="${changeClass(item.pct)}">${fmtSigned(item.pct, 2, '%')}</b></span>`
            : '').join('');
    }

    const read = data.market_read || {};
    $('metricVerdict').textContent = read.stance_label || '--';
    $('metricVerdict').className = `metric-value ${read.score > 0 ? 'up' : read.score < 0 ? 'down' : ''}`;
    $('metricVerdictSub').textContent = read.headline || '--';
    $('metricVerdictFoot').innerHTML = read.counts
        ? `<span>偏多 <b class="up">${read.counts.bullish}</b></span>
           <span>偏空 <b class="down">${read.counts.bearish}</b></span>
           <span>中性 <b>${read.counts.neutral}</b></span>
           <span>信心 <b>${read.confidence ?? '--'}%</b></span>`
        : '';

    const forecast = data.forecast || {};
    const ensemble = forecast.ensemble;
    if (ensemble) {
        $('metricForecast').textContent = fmtPrice(ensemble.predicted_price);
        const sub = $('metricForecastSub');
        sub.className = `metric-sub ${changeClass(ensemble.change_pct)}`;
        sub.textContent = `${forecast.horizon_days} 日後 ${fmtSigned(ensemble.change_pct, 2, '%')}`;
        $('metricForecastFoot').innerHTML =
            `<span>回測方向準確 <b>${ensemble.directional_accuracy ?? '--'}%</b></span>
             <span>區間 <b>${fmtPrice(ensemble.lower_band?.at(-1))} ~ ${fmtPrice(ensemble.upper_band?.at(-1))}</b></span>`;
    } else {
        $('metricForecast').textContent = '--';
        $('metricForecastSub').textContent = forecast.message || '資料不足，無法建模';
        $('metricForecastFoot').innerHTML = '';
    }

    const summary = data.news_summary;
    if (summary && summary.records) {
        const labelMap = { positive: '偏正面', negative: '偏負面', neutral: '中立' };
        $('metricSentiment').textContent = labelMap[summary.dominant_label] || '中立';
        $('metricSentiment').className = `metric-value ${summary.dominant_label === 'positive' ? 'up' : summary.dominant_label === 'negative' ? 'down' : ''}`;
        $('metricSentimentSub').textContent = `平均分數 ${Number(summary.score_mean).toFixed(1)} · ${summary.records} 則新聞`;
        $('metricSentimentFoot').innerHTML =
            `<span>正面 <b class="up">${Math.round(summary.positive_ratio * 100)}%</b></span>
             <span>負面 <b class="down">${Math.round(summary.negative_ratio * 100)}%</b></span>
             <span>中立 <b>${Math.round(summary.neutral_ratio * 100)}%</b></span>`;
    } else {
        $('metricSentiment').textContent = '--';
        $('metricSentiment').className = 'metric-value';
        $('metricSentimentSub').textContent = '暫時沒有新聞資料';
        $('metricSentimentFoot').innerHTML = '';
    }
}

/* ----------------------------- 市場判讀 ----------------------------- */
function renderMarketRead(read) {
    if (!read) return;

    const score = Number(read.score || 0);
    const arc = $('gaugeArc');
    const total = 251.3; // 半圓弧長（r=80）
    const ratio = Math.min(1, Math.max(0, (score + 100) / 200));
    arc.setAttribute('stroke-dasharray', `${(total * ratio).toFixed(1)} ${total}`);
    arc.style.stroke = score >= 12 ? cssVar('--up') : score <= -12 ? cssVar('--down') : cssVar('--text-subtle');

    const gaugeValue = $('gaugeValue');
    gaugeValue.textContent = fmtSigned(score, 0);
    gaugeValue.className = `gauge-value ${changeClass(score)}`;

    const badge = $('verdictBadge');
    badge.textContent = read.stance_label || '--';
    badge.dataset.stance = read.stance || 'neutral';

    $('verdictCounts').innerHTML = read.counts
        ? `<span>偏多 <b class="up">${read.counts.bullish}</b></span>
           <span>偏空 <b class="down">${read.counts.bearish}</b></span>
           <span>中性 <b>${read.counts.neutral}</b></span>`
        : '';

    $('readHeadline').textContent = read.headline || '';
    $('readSummary').textContent = read.summary || '';
    $('readUpdatedAt').textContent = `信心 ${read.confidence ?? '--'}%`;

    const risk = $('readRisk');
    if (read.risk_note) {
        risk.hidden = false;
        $('readRiskText').textContent = read.risk_note;
    } else {
        risk.hidden = true;
    }

    const stanceOrder = { bullish: 0, bearish: 1, neutral: 2 };
    const signals = [...(read.signals || [])].sort((a, b) =>
        (stanceOrder[a.stance] - stanceOrder[b.stance]) || (b.strength - a.strength));

    $('signalGrid').innerHTML = signals.map((signal) => `
        <article class="signal" data-stance="${escapeHtml(signal.stance)}">
            <div class="signal-head">
                <span class="signal-name">${escapeHtml(signal.name)}</span>
                <span class="signal-stance">${escapeHtml(signal.stance_label)}</span>
            </div>
            <div class="signal-value">${escapeHtml(signal.value_text || '')}</div>
            <div class="strength-track"><div class="strength-fill" style="width:${signal.strength}%"></div></div>
            <p class="signal-text">${escapeHtml(signal.text)}</p>
        </article>`).join('');

    if (read.disclaimer) $('disclaimer').textContent = read.disclaimer;
}

/* ----------------------------- 圖表 ----------------------------- */
function futureLabels(lastLabel, count) {
    const labels = [];
    const isIntraday = String(lastLabel).includes(':');
    const cursor = new Date(String(lastLabel).replace(' ', 'T'));
    if (Number.isNaN(cursor.getTime())) {
        for (let i = 1; i <= count; i += 1) labels.push(`+${i}`);
        return labels;
    }
    for (let i = 0; i < count; i += 1) {
        if (isIntraday) {
            cursor.setHours(cursor.getHours() + 1);
        } else {
            cursor.setDate(cursor.getDate() + 1);
            while (cursor.getDay() === 0 || cursor.getDay() === 6) cursor.setDate(cursor.getDate() + 1);
        }
        labels.push(isIntraday
            ? `${cursor.toISOString().slice(0, 10)} ${String(cursor.getHours()).padStart(2, '0')}:00`
            : cursor.toISOString().slice(0, 10));
    }
    return labels;
}

function tickValues(labels) {
    if (!labels.length) return [];
    const target = window.innerWidth < 768 ? 4 : 8;
    const step = Math.max(1, Math.ceil(labels.length / target));
    const ticks = labels.filter((_, index) => index % step === 0);
    if (ticks[ticks.length - 1] !== labels[labels.length - 1]) ticks.push(labels[labels.length - 1]);
    return ticks;
}

function baseLayout(labels, height, { rangeslider = false, extraYAxis = null } = {}) {
    const theme = chartTheme();
    const layout = {
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: theme.text, family: 'Inter, "Noto Sans TC", system-ui', size: 11 },
        autosize: true,
        height,
        margin: { l: 12, r: 58, t: 10, b: 34 },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: theme.surface, bordercolor: theme.grid, font: { color: cssVar('--text') } },
        showlegend: true,
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 10 } },
        xaxis: {
            type: 'category',
            categoryorder: 'array',
            categoryarray: labels,
            gridcolor: theme.grid,
            linecolor: theme.grid,
            zeroline: false,
            tickmode: 'array',
            tickvals: tickValues(labels),
            automargin: true,
            rangeslider: rangeslider ? { visible: true, thickness: 0.06, bgcolor: 'rgba(0,0,0,0)' } : { visible: false },
        },
        yaxis: { gridcolor: theme.grid, zeroline: false, side: 'right', automargin: true },
    };
    if (extraYAxis) layout.yaxis2 = extraYAxis;
    return layout;
}

const PLOT_CONFIG = { displayModeBar: false, responsive: true, doubleClick: 'reset' };

function renderCharts() {
    const data = state.data;
    if (!data || typeof Plotly === 'undefined') return;
    drawMainChart(data);
    drawSubCharts(data);
    if (data.corporate_actions?.dividends) drawDividendChart(data.corporate_actions.dividends);
    if (data.dca?.status === 'ready') drawDcaChart(data.dca, state.dcaAmount / (data.dca.unit_amount || DCA_UNIT));
    if (state.compareData) drawCompareChart(state.compareData);
}

function drawMainChart(data) {
    const theme = chartTheme();
    const prices = data.stock_price_trends || [];
    const indicators = data.technical_indicators || {};
    const labels = prices.map((item) => item.date);
    const axisLabels = [...labels];

    const traces = [{
        type: 'candlestick',
        name: data.symbol?.display_code || state.ticker,
        x: labels,
        open: prices.map((p) => p.open),
        high: prices.map((p) => p.high),
        low: prices.map((p) => p.low),
        close: prices.map((p) => p.close),
        increasing: { line: { color: theme.up, width: 1 }, fillcolor: theme.up },
        decreasing: { line: { color: theme.down, width: 1 }, fillcolor: theme.down },
    }];

    let extraYAxis = null;
    if (state.overlays.has('volume')) {
        const volumes = prices.map((p) => p.volume || 0);
        const maxVolume = Math.max(...volumes, 1);
        traces.push({
            type: 'bar', name: '成交量', x: labels, y: volumes, yaxis: 'y2',
            marker: {
                color: prices.map((p, index) => {
                    const previous = prices[index - 1];
                    return !previous || p.close >= previous.close ? theme.up : theme.down;
                }),
                opacity: 0.28,
            },
            hovertemplate: '%{y:,.0f}<extra>成交量</extra>',
        });
        extraYAxis = { overlaying: 'y', side: 'left', showgrid: false, visible: false, range: [0, maxVolume * 4.5] };
    }

    if (state.overlays.has('ma')) {
        const palette = { sma5: theme.accent, sma20: theme.warn, sma60: theme.info, sma120: theme.up, sma240: theme.down };
        ['sma5', 'sma20', 'sma60', 'sma120', 'sma240'].forEach((key) => {
            const series = indicators.sma?.[key];
            if (!series || series.every((value) => value === null)) return;
            traces.push({
                type: 'scatter', mode: 'lines', name: key.toUpperCase().replace('SMA', 'MA'),
                x: labels, y: series, line: { color: palette[key], width: 1.2 },
            });
        });
    }

    if (state.overlays.has('bb') && indicators.bb) {
        traces.push(
            { type: 'scatter', mode: 'lines', name: 'BB 上軌', x: labels, y: indicators.bb.upper, line: { color: theme.text, width: 1, dash: 'dot' } },
            {
                type: 'scatter', mode: 'lines', name: 'BB 下軌', x: labels, y: indicators.bb.lower,
                line: { color: theme.text, width: 1, dash: 'dot' },
                fill: 'tonexty', fillcolor: 'rgba(148,163,184,0.10)',
            },
        );
    }

    const ensemble = data.forecast?.ensemble;
    if (state.overlays.has('forecast') && ensemble?.path?.length) {
        const future = futureLabels(labels[labels.length - 1], ensemble.path.length);
        axisLabels.push(...future);
        const anchor = prices[prices.length - 1]?.close ?? null;
        const bridge = [labels[labels.length - 1], ...future];

        traces.push(
            {
                type: 'scatter', mode: 'lines', name: '預測上緣', x: bridge,
                y: [anchor, ...ensemble.upper_band], line: { color: 'rgba(0,0,0,0)' }, hoverinfo: 'skip', showlegend: false,
            },
            {
                type: 'scatter', mode: 'lines', name: '80% 信賴區間', x: bridge,
                y: [anchor, ...ensemble.lower_band], line: { color: 'rgba(0,0,0,0)' },
                fill: 'tonexty', fillcolor: 'rgba(56,189,248,0.16)', hoverinfo: 'skip',
            },
            {
                type: 'scatter', mode: 'lines+markers', name: `預測 ${data.forecast.horizon_days} 日`,
                x: bridge, y: [anchor, ...ensemble.path],
                line: { color: theme.warn, width: 2, dash: 'dash' }, marker: { size: 4 },
            },
        );
    }

    const layout = baseLayout(axisLabels, 560, { extraYAxis });
    Plotly.react('mainChart', traces, layout, PLOT_CONFIG);
}

const SUBCHART_META = {
    macd: { title: 'MACD 指標', height: 200 },
    rsi: { title: 'RSI 相對強弱', height: 190 },
    kd: { title: 'KD 隨機指標', height: 190 },
    bias: { title: 'BIAS 乖離率', height: 180 },
    ad: { title: 'A/D 累積派發線', height: 180 },
};

function drawSubCharts(data) {
    const container = $('subCharts');
    const active = Array.from(state.subcharts);
    const prices = data.stock_price_trends || [];
    const indicators = data.technical_indicators || {};
    const labels = prices.map((item) => item.date);

    container.innerHTML = active.map((key) => `
        <div class="subchart">
            <div class="subchart-title">${SUBCHART_META[key]?.title || key.toUpperCase()}</div>
            <div id="subchart-${key}" style="height:${SUBCHART_META[key]?.height || 190}px"></div>
        </div>`).join('');

    const theme = chartTheme();
    active.forEach((key) => {
        const target = `subchart-${key}`;
        const height = SUBCHART_META[key]?.height || 190;
        let traces = [];

        if (key === 'macd' && indicators.macd) {
            traces = [
                {
                    type: 'bar', name: '柱狀體', x: labels, y: indicators.macd.histogram,
                    marker: { color: indicators.macd.histogram.map((v) => (v >= 0 ? theme.up : theme.down)), opacity: 0.6 },
                },
                { type: 'scatter', mode: 'lines', name: 'MACD', x: labels, y: indicators.macd.macd, line: { color: theme.accent, width: 1.4 } },
                { type: 'scatter', mode: 'lines', name: '訊號線', x: labels, y: indicators.macd.signal, line: { color: theme.warn, width: 1.4 } },
            ];
        } else if (key === 'rsi') {
            traces = [
                { type: 'scatter', mode: 'lines', name: 'RSI', x: labels, y: indicators.rsi, line: { color: theme.info, width: 1.6 } },
                { type: 'scatter', mode: 'lines', name: '70 超買', x: labels, y: labels.map(() => 70), line: { color: theme.down, width: 1, dash: 'dash' } },
                { type: 'scatter', mode: 'lines', name: '30 超賣', x: labels, y: labels.map(() => 30), line: { color: theme.up, width: 1, dash: 'dash' } },
            ];
        } else if (key === 'kd' && indicators.kd) {
            traces = [
                { type: 'scatter', mode: 'lines', name: 'K', x: labels, y: indicators.kd.k, line: { color: theme.warn, width: 1.5 } },
                { type: 'scatter', mode: 'lines', name: 'D', x: labels, y: indicators.kd.d, line: { color: theme.info, width: 1.5 } },
            ];
        } else if (key === 'bias') {
            traces = [
                { type: 'scatter', mode: 'lines', name: 'BIAS 20', x: labels, y: indicators.bias, line: { color: theme.accent, width: 1.5 }, fill: 'tozeroy', fillcolor: 'rgba(56,189,248,0.10)' },
            ];
        } else if (key === 'ad') {
            traces = [
                { type: 'scatter', mode: 'lines', name: 'A/D（百萬）', x: labels, y: (indicators.ad || []).map((v) => (v === null ? null : v / 1e6)), line: { color: theme.up, width: 1.5 } },
            ];
        }

        if (traces.length) {
            const layout = baseLayout(labels, height);
            layout.margin = { l: 12, r: 58, t: 6, b: 26 };
            Plotly.react(target, traces, layout, PLOT_CONFIG);
        }
    });
}

/* ----------------------------- 預測面板 ----------------------------- */
function renderForecast(forecast) {
    const body = $('modelTableBody');
    $('forecastHorizonLabel').textContent = forecast?.horizon_days ?? state.horizon;

    if (!forecast || forecast.status !== 'ready') {
        $('forecastPrice').textContent = '--';
        $('forecastChange').textContent = forecast?.message || '歷史資料不足，無法建立預測模型';
        $('forecastMeta').textContent = '';
        body.innerHTML = `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem;">
            請改用較長的時間範圍（例如 1 年以上）再試一次</td></tr>`;
        return;
    }

    const ensemble = forecast.ensemble;
    $('forecastPrice').textContent = fmtPrice(ensemble.predicted_price);
    const change = $('forecastChange');
    change.className = `metric-sub ${changeClass(ensemble.change_pct)}`;
    change.textContent = `相對現價 ${fmtSigned(ensemble.change_pct, 2, '%')} · 80% 信賴區間 ${fmtPrice(ensemble.lower_band.at(-1))} ~ ${fmtPrice(ensemble.upper_band.at(-1))}`;

    const validation = forecast.validation || {};
    $('forecastMeta').innerHTML =
        `<div>滾動回測 <b>${validation.runs ?? 0}</b> 次</div>
         <div>最佳單一模型 <b>${escapeHtml(validation.best_model || '--')}</b>（誤差 ${validation.best_model_mape ?? '--'}%）</div>
         <div>方向準確率 <b>${validation.weighted_directional_accuracy ?? '--'}%</b></div>
         <div>樣本 <b>${forecast.sample_size}</b> 筆 · 日波動 <b>${forecast.volatility_daily_pct}%</b></div>`;

    const rows = Object.values(forecast.predictions || {});
    body.innerHTML = [
        renderModelRow({ ...ensemble, weight: 100, isEnsemble: true }),
        ...rows.map((row) => renderModelRow(row)),
    ].join('');
}

function renderModelRow(row) {
    const weight = Number(row.weight || 0);
    return `
        <tr${row.isEnsemble ? ' style="background:var(--accent-soft)"' : ''}>
            <td class="model-name">${escapeHtml(row.model)}</td>
            <td>${fmtPrice(row.predicted_price)}</td>
            <td class="${changeClass(row.change_pct)}">${fmtSigned(row.change_pct, 2, '%')}</td>
            <td>${row.backtest_mape != null ? `${row.backtest_mape}%` : '--'}</td>
            <td>${row.directional_accuracy != null ? `${row.directional_accuracy}%` : '--'}</td>
            <td>
                <span class="weight-cell">
                    <span class="weight-bar"><span style="width:${Math.min(100, weight)}%"></span></span>
                    ${weight ? `${weight}%` : '--'}
                </span>
            </td>
        </tr>`;
}

/* ----------------------------- 概況 ----------------------------- */
function renderOverview(overview, symbol) {
    const container = $('overviewSections');
    const kindTag = $('overviewKind');

    if (!overview) {
        container.innerHTML = '<div class="empty-state">暫時無法取得標的概況</div>';
        kindTag.textContent = '--';
        $('companyDesc').textContent = '';
        $('descToggle').hidden = true;
        return;
    }

    const isEtf = overview.kind === 'etf';
    kindTag.textContent = overview.kind_label || '標的';
    kindTag.dataset.kind = overview.kind || '';
    $('overviewTitle').textContent = `${overview.name || symbol?.display_code || ''} 基本資料`;
    $('overviewSubtitle').textContent = isEtf
        ? 'ETF：規模、費用率、追蹤績效與配息條件'
        : '個股：公司基本資料、評價、獲利能力與配息';

    const pct = (value) => (value === null || value === undefined ? null : fmtPercentFromRatio(value));
    const fixed = (value, digits = 2) => (value === null || value === undefined || value === ''
        ? null : Number(value).toFixed(digits));

    const sections = isEtf ? [
        ['基本資料', [
            ['代號', overview.symbol],
            ['交易所', overview.exchange],
            ['計價幣別', overview.currency],
            ['發行商', overview.fund_family],
            ['類別', overview.category],
            ['基金型態', overview.legal_type],
            ['成立日期', overview.inception_date],
        ]],
        ['規模與成本', [
            ['資產規模', fmtCompact(overview.total_assets)],
            ['費用率', pct(overview.expense_ratio)],
            ['淨值 NAV', overview.nav_price != null ? fmtPrice(overview.nav_price) : null],
            ['週轉率', pct(overview.holdings_turnover)],
            ['Beta', fixed(overview.beta)],
        ]],
        ['績效與配息', [
            ['今年報酬', pct(overview.ytd_return)],
            ['三年平均', pct(overview.three_year_return)],
            ['五年平均', pct(overview.five_year_return)],
            ['近一年漲跌', overview.fifty_two_week_change_pct != null ? `${overview.fifty_two_week_change_pct}%` : null],
            ['配息率', pct(overview.dividend_yield)],
            ['每股配息(年)', fixed(overview.dividend_rate)],
            ['前次除息日', overview.ex_dividend_date],
        ]],
        ['交易資訊', [
            ['52週最高', overview.fifty_two_week_high != null ? fmtPrice(overview.fifty_two_week_high) : null],
            ['52週最低', overview.fifty_two_week_low != null ? fmtPrice(overview.fifty_two_week_low) : null],
            ['平均量(3個月)', fmtCompact(overview.average_volume)],
            ['平均量(10日)', fmtCompact(overview.average_volume_10d)],
        ]],
    ] : [
        ['公司基本資料', [
            ['代號', overview.symbol],
            ['交易所', overview.exchange],
            ['計價幣別', overview.currency],
            ['產業', overview.sector],
            ['次產業', overview.industry],
            ['所在地', [overview.city, overview.country].filter(Boolean).join('、') || null],
            ['員工數', overview.employees != null ? fmtCompact(overview.employees) : null],
            ['流通股數', fmtCompact(overview.shares_outstanding)],
        ]],
        ['評價指標', [
            ['市值', fmtCompact(overview.market_cap)],
            ['本益比 PE', fixed(overview.trailing_pe)],
            ['預估本益比', fixed(overview.forward_pe)],
            ['PEG', fixed(overview.peg_ratio)],
            ['股價淨值比 PB', fixed(overview.price_to_book)],
            ['股價營收比 PS', fixed(overview.price_to_sales)],
            ['每股淨值', fixed(overview.book_value)],
            ['Beta', fixed(overview.beta)],
        ]],
        ['獲利能力', [
            ['EPS(近四季)', fixed(overview.eps)],
            ['EPS(預估)', fixed(overview.forward_eps)],
            ['營收', fmtCompact(overview.total_revenue)],
            ['毛利率', pct(overview.gross_margin)],
            ['營業利益率', pct(overview.operating_margin)],
            ['淨利率', pct(overview.profit_margin)],
            ['ROE', pct(overview.roe)],
            ['ROA', pct(overview.roa)],
            ['營收成長', pct(overview.revenue_growth)],
            ['盈餘成長', pct(overview.earnings_growth)],
            ['自由現金流', fmtCompact(overview.free_cashflow)],
            ['負債權益比', fixed(overview.debt_to_equity)],
            ['流動比率', fixed(overview.current_ratio)],
        ]],
        ['配息與交易', [
            ['現金殖利率', pct(overview.dividend_yield)],
            ['每股股利(年)', fixed(overview.dividend_rate)],
            ['五年平均殖利率', overview.five_year_avg_dividend_yield != null ? `${Number(overview.five_year_avg_dividend_yield).toFixed(2)}%` : null],
            ['盈餘配發率', pct(overview.payout_ratio)],
            ['前次除息日', overview.ex_dividend_date],
            ['52週最高', overview.fifty_two_week_high != null ? fmtPrice(overview.fifty_two_week_high) : null],
            ['52週最低', overview.fifty_two_week_low != null ? fmtPrice(overview.fifty_two_week_low) : null],
            ['近一年漲跌', overview.fifty_two_week_change_pct != null ? `${overview.fifty_two_week_change_pct}%` : null],
            ['平均量(3個月)', fmtCompact(overview.average_volume)],
        ]],
    ];

    const html = sections.map(([title, rows]) => {
        const visible = rows.filter(([, value]) =>
            value !== null && value !== undefined && value !== '' && value !== '--');
        if (!visible.length) return '';
        return `<div class="section-label">${escapeHtml(title)}</div>
            <dl class="kv-grid">${visible.map(([label, value]) =>
                `<div class="kv"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl>`;
    }).join('');

    container.innerHTML = html || '<div class="empty-state">此標的沒有提供詳細資料</div>';

    const desc = $('companyDesc');
    const toggle = $('descToggle');
    if (overview.description) {
        desc.textContent = overview.description;
        desc.classList.remove('expanded');
        toggle.hidden = false;
        toggle.textContent = '顯示完整介紹';
    } else {
        desc.textContent = '';
        toggle.hidden = true;
    }
}

/* ----------------------------- 配息與分割 ----------------------------- */
function renderCorporateActions(actions, overview) {
    const statsEl = $('dividendStats');
    const tagEl = $('dividendFrequency');
    const wrapEl = $('actionTableWrap');
    const currency = overview?.currency || '';
    const dividends = actions?.dividends;
    const splits = actions?.splits;

    els('[data-action-tab]').forEach((button) => {
        const key = button.dataset.actionTab;
        button.setAttribute('aria-pressed', String(key === state.actionTab));
        button.disabled = key === 'splits' ? !splits : !dividends;
    });

    if (!dividends) {
        tagEl.textContent = splits ? '無配息' : '無紀錄';
        statsEl.innerHTML = '';
        $('dividendSubtitle').textContent = actions?.status === 'unavailable'
            ? '暫時無法取得配息資料'
            : '這檔標的在 Yahoo Finance 沒有配息紀錄（常見於不配息個股或剛上市的 ETF）';
        clearChart('dividendChart');
        wrapEl.innerHTML = splits
            ? renderSplitTable(splits)
            : '<div class="empty-state">沒有配息或分割紀錄</div>';
        return;
    }

    tagEl.textContent = dividends.frequency_label || '—';
    $('dividendSubtitle').textContent =
        `${dividends.first_date} 起共 ${dividends.total_records} 次配息紀錄`;

    statsEl.innerHTML = [
        ['近12個月配息', `${fmtPrice(dividends.ttm_total, 2)}`, currency],
        ['現金殖利率', dividends.ttm_yield_pct != null ? `${dividends.ttm_yield_pct}%` : '--', '以現價計算'],
        ['近三年平均', dividends.average_3y != null ? fmtPrice(dividends.average_3y, 2) : '--', '每年配息'],
        ['連續配息', `${dividends.consecutive_years} 年`, `累計 ${dividends.years_paid} 年有配息`],
        ['最近除息', dividends.latest?.date || '--', `配 ${fmtPrice(dividends.latest?.amount, 2)}`],
    ].map(([label, value, note]) => `
        <div class="stat-chip">
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value)}</dd>
            <small>${escapeHtml(note || '')}</small>
        </div>`).join('');

    drawDividendChart(dividends);
    renderActionTable(dividends, splits, currency);
}

function drawDividendChart(dividends) {
    if (typeof Plotly === 'undefined') return;
    const theme = chartTheme();
    const years = dividends.yearly.map((item) => String(item.year));
    const totals = dividends.yearly.map((item) => item.total);

    const trace = {
        type: 'bar',
        x: years,
        y: totals,
        marker: {
            color: totals.map((_, index) => (index === totals.length - 1 ? theme.warn : theme.accent)),
            opacity: 0.85,
        },
        hovertemplate: '%{x} 年：%{y:.2f}<extra>合計配息</extra>',
        name: '每年配息',
    };

    const layout = baseLayout(years, 210);
    layout.margin = { l: 12, r: 52, t: 8, b: 28 };
    layout.showlegend = false;
    layout.xaxis.tickvals = years;
    Plotly.react('dividendChart', [trace], layout, PLOT_CONFIG);
}

function clearChart(id) {
    const node = $(id);
    if (node && typeof Plotly !== 'undefined') Plotly.purge(node);
    if (node) node.innerHTML = '';
}

function renderActionTable(dividends, splits, currency) {
    const wrap = $('actionTableWrap');
    if (state.actionTab === 'splits') {
        wrap.innerHTML = splits ? renderSplitTable(splits) : '<div class="empty-state">沒有股票分割紀錄</div>';
        return;
    }
    if (!dividends) {
        wrap.innerHTML = '<div class="empty-state">沒有配息紀錄</div>';
        return;
    }
    wrap.innerHTML = `
        <table class="data-table">
            <thead><tr><th>除息日</th><th>配息金額${currency ? `（${escapeHtml(currency)}）` : ''}</th><th>當年度累計</th></tr></thead>
            <tbody>
                ${dividends.records.map((record) => {
                    const year = record.date.slice(0, 4);
                    const yearTotal = dividends.yearly.find((item) => String(item.year) === year);
                    return `<tr>
                        <td>${escapeHtml(record.date)}</td>
                        <td>${fmtPrice(record.amount, 2)}</td>
                        <td class="muted">${yearTotal ? fmtPrice(yearTotal.total, 2) : '--'}</td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
}

function renderSplitTable(splits) {
    return `
        <table class="data-table">
            <thead><tr><th>日期</th><th>內容</th><th>比例</th></tr></thead>
            <tbody>
                ${splits.records.map((record) => `
                    <tr>
                        <td>${escapeHtml(record.date)}</td>
                        <td style="text-align:left">${escapeHtml(record.label)}</td>
                        <td>${record.ratio}</td>
                    </tr>`).join('')}
            </tbody>
        </table>`;
}

/* ----------------------------- 延伸資料 ----------------------------- */
function renderExtraPanel(data) {
    const body = $('extraBody');
    const overview = data.company_overview || {};
    const isEtf = overview.kind === 'etf';
    const profile = data.fund_profile;

    if (isEtf) {
        $('extraTitle').textContent = 'ETF 持股與產業分布';
        $('extraSubtitle').textContent = '看清楚這檔 ETF 實際買了什麼';

        if (!profile || (!profile.top_holdings?.length && !profile.sector_weightings?.length)) {
            body.innerHTML = '<div class="empty-state">Yahoo Finance 沒有提供這檔 ETF 的成分資料</div>';
            return;
        }

        const holdings = profile.top_holdings?.length ? `
            <div class="section-label">前十大持股</div>
            ${profile.top_holdings.map((item) => `
                <div class="holding">
                    <span class="code">${escapeHtml(item.symbol || '')}</span>
                    <span class="name">${escapeHtml(item.name || '')}</span>
                    <span class="weight">${item.weight_pct != null ? `${Number(item.weight_pct).toFixed(2)}%` : '--'}</span>
                </div>`).join('')}` : '';

        const sectors = profile.sector_weightings?.length ? `
            <div class="section-label">產業分布</div>
            ${profile.sector_weightings.map((item) => `
                <div class="bar-row">
                    <div class="bar-head"><span>${escapeHtml(item.sector)}</span><b>${Number(item.weight_pct).toFixed(1)}%</b></div>
                    <div class="bar-track"><span style="width:${Math.min(100, Number(item.weight_pct))}%"></span></div>
                </div>`).join('')}` : '';

        body.innerHTML = holdings + sectors;
        return;
    }

    $('extraTitle').textContent = '分析師評等與重要日期';
    $('extraSubtitle').textContent = '法人目標價、財報與除息時間';

    const recommendationMap = {
        strong_buy: '強力買進', buy: '買進', hold: '中立',
        sell: '賣出', strong_sell: '強力賣出', underperform: '弱於大盤', outperform: '優於大盤',
    };
    const latestClose = data.stock_price_trends?.at(-1)?.close;
    const target = overview.target_mean_price;
    const upside = (target && latestClose) ? ((target - latestClose) / latestClose * 100) : null;

    const rows = [
        ['分析師評等', overview.recommendation ? (recommendationMap[overview.recommendation] || overview.recommendation) : null],
        ['分析師人數', overview.analyst_count],
        ['平均目標價', target != null ? fmtPrice(target) : null],
        ['距目標價', upside != null ? `${fmtSigned(upside, 1, '%')}` : null],
        ['下次財報日', overview.earnings_date],
        ['前次除息日', overview.ex_dividend_date],
        ['前次分割', overview.last_split_date ? `${overview.last_split_date}（${overview.last_split_factor || '--'}）` : null],
        ['前一日收盤', overview.previous_close != null ? fmtPrice(overview.previous_close) : null],
    ].filter(([, value]) => value !== null && value !== undefined && value !== '');

    body.innerHTML = rows.length
        ? `<dl class="kv-grid">${rows.map(([label, value]) =>
            `<div class="kv"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join('')}</dl>`
        : '<div class="empty-state">Yahoo Finance 沒有提供這檔個股的評等資料</div>';
}

/* ----------------------------- 風險與報酬 ----------------------------- */
function renderRisk(risk, symbol) {
    const stats = $('riskStats');
    const note = $('riskNote');
    const betaTag = $('riskBeta');

    if (!risk || risk.status !== 'ready') {
        stats.innerHTML = '';
        betaTag.textContent = '--';
        note.textContent = '資料筆數不足，無法計算風險指標，請改用較長的時間範圍。';
        return;
    }

    $('riskSubtitle').textContent = `${risk.start_date} ~ ${risk.end_date}（共 ${risk.sample_size} 筆）`;
    betaTag.textContent = risk.benchmark
        ? `Beta ${risk.benchmark.beta}（對 ${risk.benchmark.label}）`
        : '無對照基準';

    const rows = [
        ['期間報酬', fmtSigned(risk.total_return_pct, 2, '%'), '買進並持有', changeClass(risk.total_return_pct)],
        ['年化報酬', fmtSigned(risk.annualized_return_pct, 2, '%'), '換算成一年', changeClass(risk.annualized_return_pct)],
        ['年化波動', `${risk.annualized_volatility_pct}%`, '數字越大越震盪', ''],
        ['最大回撤', `${risk.max_drawdown_pct}%`, `${risk.max_drawdown_peak_date} → ${risk.max_drawdown_trough_date}`, 'down'],
        ['夏普值', risk.sharpe_ratio ?? '--', '每承受 1 單位風險的報酬', ''],
        ['索提諾值', risk.sortino_ratio ?? '--', '只看下跌風險', ''],
        ['上漲月份', risk.monthly_win_rate_pct != null ? `${risk.monthly_win_rate_pct}%` : '--', '月線收紅的比例', ''],
        ['單日最大漲跌', `${fmtSigned(risk.best_period_pct, 2, '%')} / ${fmtSigned(risk.worst_period_pct, 2, '%')}`, '期間內極值', ''],
    ];

    stats.innerHTML = rows.map(([label, value, hint, cls]) => `
        <div class="stat-chip">
            <dt>${escapeHtml(label)}</dt>
            <dd class="${cls}">${escapeHtml(value)}</dd>
            <small>${escapeHtml(hint)}</small>
        </div>`).join('');

    const sharpeText = risk.sharpe_ratio == null ? '無法計算夏普值'
        : risk.sharpe_ratio >= 1 ? `夏普值 ${risk.sharpe_ratio}，報酬相對於承受的風險算是不錯`
        : risk.sharpe_ratio >= 0 ? `夏普值 ${risk.sharpe_ratio}，報酬只勉強補償了波動`
        : `夏普值 ${risk.sharpe_ratio}，這段期間承受風險卻沒有換到報酬`;
    const betaText = risk.benchmark
        ? (risk.benchmark.beta >= 1.2 ? `Beta ${risk.benchmark.beta}，波動比${risk.benchmark.label}更劇烈`
            : risk.benchmark.beta <= 0.8 ? `Beta ${risk.benchmark.beta}，比${risk.benchmark.label}抗跌`
            : `Beta ${risk.benchmark.beta}，走勢大致跟著${risk.benchmark.label}`)
        : '';
    note.textContent =
        `這段期間最深曾經從高點下跌 ${Math.abs(risk.max_drawdown_pct)}%（${risk.max_drawdown_peak_date} 到 ${risk.max_drawdown_trough_date}），`
        + `年化波動 ${risk.annualized_volatility_pct}%。${sharpeText}。${betaText ? betaText + '。' : ''}`;
}

/* ----------------------------- 定期定額試算 ----------------------------- */
function renderDca(dca, overview) {
    const stats = $('dcaStats');
    const note = $('dcaNote');

    if (!dca || dca.status !== 'ready') {
        stats.innerHTML = '';
        note.textContent = '資料筆數不足，無法試算（建議選 1 年以上的範圍）。';
        clearChart('dcaChart');
        return;
    }

    const scale = state.dcaAmount / (dca.unit_amount || DCA_UNIT);
    const currency = overview?.currency || '';
    const invested = dca.invested * scale;
    const finalValue = dca.final_value * scale;
    const profit = dca.profit * scale;
    const dividends = dca.dividend_total * scale;
    const lumpSum = dca.lump_sum_value != null ? dca.lump_sum_value * scale : null;

    $('dcaSubtitle').textContent =
        `${dca.start_date} 起每月投入，共 ${dca.months} 期（約 ${dca.years} 年）`;

    const rows = [
        ['累計投入', fmtPrice(invested, 0), currency, ''],
        ['目前價值', fmtPrice(finalValue, 0), currency, ''],
        ['總損益', fmtSignedAmount(profit), `${fmtSigned(dca.total_return_pct, 2, '%')}`, changeClass(profit)],
        ['年化報酬', fmtSigned(dca.annualized_return_pct, 2, '%'), '以投入時間加權', changeClass(dca.annualized_return_pct)],
        ['累計配息', fmtPrice(dividends, 0), dca.dividend_reinvested ? '已再投入' : '未再投入', ''],
        ['平均成本', fmtPrice(dca.average_cost, 2), `現價 ${fmtPrice(dca.final_price, 2)}`, ''],
    ];

    stats.innerHTML = rows.map(([label, value, hint, cls]) => `
        <div class="stat-chip">
            <dt>${escapeHtml(label)}</dt>
            <dd class="${cls}">${escapeHtml(value)}</dd>
            <small>${escapeHtml(hint)}</small>
        </div>`).join('');

    drawDcaChart(dca, scale);

    const compareText = lumpSum != null
        ? `同樣金額在第一天一次全部投入會變成 ${fmtPrice(lumpSum, 0)}（${lumpSum > finalValue ? '一次投入較佳' : '定期定額較佳'}）。`
        : '';
    note.textContent =
        `試算以每月第一個交易日收盤價買進、可買零股為前提，${dca.dividend_reinvested ? '配息自動再投入' : '配息以現金保留'}；`
        + `未計入手續費與稅。${compareText}過去績效不代表未來報酬。`;
}

function drawDcaChart(dca, scale) {
    if (typeof Plotly === 'undefined' || !dca.history?.length) return;
    const theme = chartTheme();
    const dates = dca.history.map((item) => item.date);

    const traces = [
        {
            type: 'scatter', mode: 'lines', name: '累計投入', x: dates,
            y: dca.history.map((item) => Math.round(item.invested * scale)),
            line: { color: theme.text, width: 1.4, dash: 'dot' },
        },
        {
            type: 'scatter', mode: 'lines', name: '資產價值', x: dates,
            y: dca.history.map((item) => Math.round(item.value * scale)),
            line: { color: theme.accent, width: 2 },
            fill: 'tonexty', fillcolor: 'rgba(56,189,248,0.12)',
        },
    ];

    const layout = baseLayout(dates, 190);
    layout.margin = { l: 12, r: 58, t: 6, b: 30 };
    layout.xaxis.tickangle = 0;
    Plotly.react('dcaChart', traces, layout, PLOT_CONFIG);
}

/* ----------------------------- 多標的比較 ----------------------------- */
function renderCompareChips() {
    const container = $('compareChips');
    if (!state.compareList.length) {
        container.innerHTML = '<span class="chip-label">尚未加入標的，預設會比較目前查詢的代號</span>';
        return;
    }
    container.innerHTML = `<span class="chip-label">比較中</span>` + state.compareList.map((code) => `
        <button class="chip active" type="button" data-compare-remove="${escapeHtml(code)}">
            ${escapeHtml(code)}<span class="remove">×</span>
        </button>`).join('');

    els('[data-compare-remove]').forEach((button) => {
        button.addEventListener('click', () => {
            state.compareList = state.compareList.filter((code) => code !== button.dataset.compareRemove);
            renderCompareChips();
            if (state.compareList.length) runCompare();
        });
    });
}

function addCompareSymbol(code) {
    const value = (code || '').trim().toUpperCase();
    if (!value) return;
    if (state.compareList.includes(value)) return;
    if (state.compareList.length >= 4) {
        toast('最多只能比較四檔標的', 'info', 3500);
        return;
    }
    state.compareList.push(value);
    renderCompareChips();
}

async function runCompare() {
    if (!state.compareList.length && state.ticker) state.compareList = [state.ticker];
    if (!state.compareList.length) return;
    renderCompareChips();

    const query = new URLSearchParams({
        tickers: state.compareList.join(','),
        period: state.period,
        interval: state.interval,
    });

    try {
        const response = await fetch(`${API.compare}?${query}`);
        const data = await response.json();
        if (!response.ok || data.status !== 'success') {
            toast(data.message || '比較失敗');
            return;
        }
        state.compareData = data;
        drawCompareChart(data);
        renderCompareTable(data);
        (data.failed || []).forEach((item) => toast(`${item.ticker}：${item.message}`, 'info', 4000));
    } catch (error) {
        toast(`比較失敗：${error.message}`);
    }
}

function drawCompareChart(data) {
    if (typeof Plotly === 'undefined') return;
    const theme = chartTheme();
    const palette = [theme.accent, theme.warn, theme.info, theme.up];
    const longest = data.series.reduce((best, item) =>
        (item.dates.length > (best?.dates.length || 0) ? item : best), null);

    const traces = data.series.map((item, index) => ({
        type: 'scatter', mode: 'lines',
        name: `${item.display_code} ${item.name || ''}`.trim(),
        x: item.dates, y: item.values,
        line: { color: palette[index % palette.length], width: 2 },
        hovertemplate: '%{y:.1f}<extra>%{fullData.name}</extra>',
    }));

    const labels = longest?.dates || [];
    traces.push({
        type: 'scatter', mode: 'lines', name: '起點 100',
        x: labels, y: labels.map(() => 100),
        line: { color: theme.text, width: 1, dash: 'dash' }, hoverinfo: 'skip', showlegend: false,
    });

    const layout = baseLayout(labels, 320);
    layout.margin = { l: 12, r: 58, t: 8, b: 30 };
    Plotly.react('compareChart', traces, layout, PLOT_CONFIG);
}

function renderCompareTable(data) {
    const wrap = $('compareTableWrap');
    const best = data.best;
    wrap.innerHTML = `
        <table class="data-table">
            <thead>
                <tr><th>標的</th><th>現價</th><th>期間報酬</th><th>年化報酬</th><th>年化波動</th><th>最大回撤</th><th>夏普值</th></tr>
            </thead>
            <tbody>
                ${data.series.map((item) => {
                    const metrics = item.metrics || {};
                    const highlight = item.display_code === best ? ' style="background:var(--accent-soft)"' : '';
                    return `<tr${highlight}>
                        <td class="model-name">${escapeHtml(item.display_code)} ${escapeHtml(item.name || '')}</td>
                        <td>${fmtPrice(item.latest_price)}</td>
                        <td class="${changeClass(metrics.total_return_pct)}">${fmtSigned(metrics.total_return_pct, 2, '%')}</td>
                        <td class="${changeClass(metrics.annualized_return_pct)}">${fmtSigned(metrics.annualized_return_pct, 2, '%')}</td>
                        <td>${metrics.annualized_volatility_pct ?? '--'}%</td>
                        <td class="down">${metrics.max_drawdown_pct ?? '--'}%</td>
                        <td>${metrics.sharpe_ratio ?? '--'}</td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
}

/* ----------------------------- 自選股 / 分享 / 匯出 ----------------------------- */
function loadWatchlist() {
    try {
        const saved = JSON.parse(safeStorage('get', STORAGE.watchlist) || '[]');
        state.watchlist = Array.isArray(saved) ? saved.slice(0, 20) : [];
    } catch (error) {
        state.watchlist = [];
    }
}

function saveWatchlist() {
    safeStorage('set', STORAGE.watchlist, JSON.stringify(state.watchlist));
}

function renderWatchlist() {
    const row = $('watchlistRow');
    row.hidden = state.watchlist.length === 0;
    row.innerHTML = '<span class="chip-label">自選</span>' + state.watchlist.map((item) => `
        <button class="chip" type="button" data-watch-code="${escapeHtml(item.code)}">
            ${escapeHtml(item.code)}${item.name ? ` ${escapeHtml(item.name)}` : ''}
            <span class="remove" data-watch-remove="${escapeHtml(item.code)}">×</span>
        </button>`).join('');

    els('[data-watch-code]').forEach((button) => {
        button.addEventListener('click', (event) => {
            if (event.target.dataset.watchRemove) {
                state.watchlist = state.watchlist.filter((item) => item.code !== event.target.dataset.watchRemove);
                saveWatchlist();
                renderWatchlist();
                updateWatchButton();
                return;
            }
            selectSuggestion(button.dataset.watchCode);
        });
    });
}

function updateWatchButton() {
    const button = $('watchBtn');
    const current = (state.data?.symbol?.display_code || state.ticker || '').toUpperCase();
    const saved = state.watchlist.some((item) => item.code === current);
    button.setAttribute('aria-pressed', String(saved));
    button.title = saved ? '從自選股移除' : '加入自選股';
}

function toggleWatch() {
    const code = (state.data?.symbol?.display_code || state.ticker || '').toUpperCase();
    if (!code) return;
    const exists = state.watchlist.some((item) => item.code === code);
    if (exists) {
        state.watchlist = state.watchlist.filter((item) => item.code !== code);
    } else {
        if (state.watchlist.length >= 20) {
            toast('自選股最多 20 檔', 'info', 3000);
            return;
        }
        state.watchlist.push({
            code,
            name: state.data?.symbol?.name_zh || state.data?.symbol?.name || '',
        });
    }
    saveWatchlist();
    renderWatchlist();
    updateWatchButton();
}

function syncUrl() {
    const params = new URLSearchParams({
        ticker: state.ticker,
        period: state.period,
        interval: state.interval,
        horizon: String(state.horizon),
    });
    window.history.replaceState(null, '', `${window.location.pathname}?${params}`);
}

function readUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const ticker = params.get('ticker');
    const period = params.get('period');
    const interval = params.get('interval');
    const horizon = Number(params.get('horizon'));
    if (ticker) state.ticker = ticker.toUpperCase();
    if (period) state.period = period;
    if (interval) state.interval = interval;
    if ([5, 7, 14, 30].includes(horizon)) state.horizon = horizon;
}

async function copyShareLink() {
    syncUrl();
    const url = window.location.href;
    try {
        await navigator.clipboard.writeText(url);
        toast('已複製分享連結', 'info', 2500);
    } catch (error) {
        toast(`請手動複製：${url}`, 'info', 8000);
    }
}

function exportCsv() {
    const data = state.data;
    if (!data?.stock_price_trends?.length) {
        toast('請先查詢資料', 'info', 2500);
        return;
    }

    const indicators = data.technical_indicators || {};
    const pick = (series, index) => (series && series[index] != null ? series[index] : '');
    const header = ['date', 'open', 'high', 'low', 'close', 'volume',
        'sma5', 'sma20', 'sma60', 'rsi', 'macd', 'macd_signal', 'k', 'd', 'bias', 'atr'];

    const rows = data.stock_price_trends.map((price, index) => [
        price.date, price.open, price.high, price.low, price.close, price.volume,
        pick(indicators.sma?.sma5, index), pick(indicators.sma?.sma20, index), pick(indicators.sma?.sma60, index),
        pick(indicators.rsi, index), pick(indicators.macd?.macd, index), pick(indicators.macd?.signal, index),
        pick(indicators.kd?.k, index), pick(indicators.kd?.d, index),
        pick(indicators.bias, index), pick(indicators.atr, index),
    ].join(','));

    const csv = `\ufeff${header.join(',')}\n${rows.join('\n')}`;
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${data.symbol?.display_code || state.ticker}_${state.period}_${state.interval}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
    toast('CSV 已開始下載', 'info', 2500);
}

/* ----------------------------- 新聞 ----------------------------- */
function renderNews(news, summary) {
    const list = $('newsList');
    const tag = $('newsModelTag');

    if (summary) {
        const statusText = summary.model_status === 'ok' ? '' : '（備援模式）';
        tag.textContent = `${summary.model_used || '--'}${statusText}`;
        tag.title = summary.model_error || summary.model_status || '';
        $('newsSubtitle').textContent = summary.records
            ? `共 ${summary.records} 則新聞 · 正面 ${Math.round(summary.positive_ratio * 100)}%、負面 ${Math.round(summary.negative_ratio * 100)}%`
            : '目前抓不到新聞資料';
    }

    if (!news || !news.length) {
        list.innerHTML = `<div class="empty-state">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 5h16v14H4z"></path><path d="M8 9h8M8 13h5"></path></svg>
            <span>目前沒有抓到相關新聞</span></div>`;
        return;
    }

    list.innerHTML = news.slice(0, 40).map((item) => {
        const sentiment = item.sentiment_label || 'neutral';
        const labelMap = { positive: '正面', negative: '負面', neutral: '中立' };
        const score = Number(item.sentiment_score || 0).toFixed(1);
        return `
            <a class="news-item" data-sentiment="${escapeHtml(sentiment)}" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
                <div class="news-title">${escapeHtml(item.headline)}</div>
                <div class="news-meta">
                    <span class="badge" data-sentiment="${escapeHtml(sentiment)}">${labelMap[sentiment]} ${score}</span>
                    <span>${escapeHtml(item.source || '')}</span>
                    <span>${escapeHtml(fmtRelativeTime(item.published_at))}</span>
                </div>
            </a>`;
    }).join('');
}

/* ----------------------------- 事件綁定 ----------------------------- */
function bindGroup(selector, attribute, handler) {
    els(selector).forEach((button) => {
        button.addEventListener('click', () => handler(button.dataset[attribute], button));
    });
}

function initEvents() {
    $('analyzeBtn').addEventListener('click', analyze);

    const input = $('tickerInput');
    const runSearch = debounce(async (value) => {
        const items = await fetchSuggestions(value);
        renderSuggestions(items);
    }, 180);

    input.addEventListener('input', (event) => runSearch(event.target.value.trim()));
    input.addEventListener('focus', () => runSearch(input.value.trim()));
    input.addEventListener('blur', () => window.setTimeout(() => openCombo(false), 120));
    input.addEventListener('keydown', (event) => {
        const open = $('comboList').dataset.open === 'true';
        if (event.key === 'ArrowDown' && open) { event.preventDefault(); highlightSuggestion(1); }
        else if (event.key === 'ArrowUp' && open) { event.preventDefault(); highlightSuggestion(-1); }
        else if (event.key === 'Escape') { openCombo(false); }
        else if (event.key === 'Enter') {
            event.preventDefault();
            const picked = state.suggestions[state.highlighted];
            if (open && picked) selectSuggestion(picked.code);
            else { openCombo(false); analyze(); }
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === '/' && document.activeElement !== input) {
            event.preventDefault();
            input.focus();
            input.select();
        }
    });

    bindGroup('[data-period]', 'period', (value) => {
        state.period = value;
        syncControls();
        savePrefs();
        analyze();
    });

    bindGroup('[data-interval]', 'interval', (value) => {
        state.interval = value;
        syncControls();
        savePrefs();
        analyze();
    });

    bindGroup('[data-horizon]', 'horizon', (value) => {
        state.horizon = Number(value);
        syncControls();
        savePrefs();
        analyze();
    });

    bindGroup('[data-overlay]', 'overlay', (value) => {
        state.overlays.has(value) ? state.overlays.delete(value) : state.overlays.add(value);
        syncControls();
        savePrefs();
        renderCharts();
    });

    bindGroup('[data-subchart]', 'subchart', (value) => {
        state.subcharts.has(value) ? state.subcharts.delete(value) : state.subcharts.add(value);
        syncControls();
        savePrefs();
        renderCharts();
    });

    bindGroup('[data-action-tab]', 'actionTab', (value) => {
        state.actionTab = value;
        els('[data-action-tab]').forEach((button) =>
            button.setAttribute('aria-pressed', String(button.dataset.actionTab === value)));
        const actions = state.data?.corporate_actions;
        renderActionTable(actions?.dividends, actions?.splits, state.data?.company_overview?.currency || '');
    });

    $('watchBtn').addEventListener('click', toggleWatch);
    $('shareBtn').addEventListener('click', copyShareLink);
    $('exportCsvBtn').addEventListener('click', exportCsv);

    const dcaInput = $('dcaAmount');
    const applyDca = () => {
        const value = Math.max(100, Number(dcaInput.value) || DCA_UNIT);
        state.dcaAmount = value;
        savePrefs();
        if (state.data?.dca) renderDca(state.data.dca, state.data.company_overview);
    };
    dcaInput.addEventListener('change', applyDca);
    dcaInput.addEventListener('input', debounce(applyDca, 400));
    els('[data-dca-step]').forEach((button) => {
        button.addEventListener('click', () => {
            dcaInput.value = String(Math.max(1000, Number(dcaInput.value || 0) + Number(button.dataset.dcaStep)));
            applyDca();
        });
    });

    $('compareBtn').addEventListener('click', () => {
        const input = $('compareInput');
        if (input.value.trim()) {
            addCompareSymbol(input.value);
            input.value = '';
        }
        runCompare();
    });
    $('compareInput').addEventListener('keydown', (event) => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        addCompareSymbol(event.target.value);
        event.target.value = '';
        runCompare();
    });

    $('descToggle').addEventListener('click', () => {
        const desc = $('companyDesc');
        const expanded = desc.classList.toggle('expanded');
        $('descToggle').textContent = expanded ? '收合介紹' : '顯示完整介紹';
    });

    window.addEventListener('resize', debounce(() => {
        if (state.data) renderCharts();
    }, 220));
}

async function initQuickPicks() {
    try {
        const response = await fetch(`${API.symbolSearch}?q=&limit=8`);
        const data = await response.json();
        const container = $('quickPicks');
        (data.quick_picks || []).forEach((item) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'chip';
            button.textContent = `${item.code} ${item.name_zh}`;
            button.addEventListener('click', () => selectSuggestion(item.code));
            container.appendChild(button);
        });
    } catch (error) {
        /* 快速選取失敗不影響主要流程 */
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    loadPrefs();
    loadWatchlist();
    readUrlParams();
    renderWatchlist();
    renderCompareChips();
    syncControls();
    initEvents();
    initQuickPicks();
    analyze();
});
