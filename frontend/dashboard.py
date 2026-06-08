from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW_NEWS = ROOT / "data" / "raw" / "news_latest.jsonl"
RAW_SUMMARY = ROOT / "data" / "raw" / "news_latest_summary.json"
NORMALIZED_NEWS = ROOT / "data" / "normalized" / "news_with_sentiment.jsonl"
NORMALIZED_SUMMARY = ROOT / "data" / "normalized" / "news_with_sentiment_summary.json"
FEATURES = ROOT / "data" / "features" / "sentiment_features_hour.csv"
RUNTIME_CONFIG = ROOT / "data" / "runtime" / "news_sources_search.json"
PORT = 8501


HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>StockSense股票預測</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: "IBM Plex Sans", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      background: #081225;
      color: #ecfeff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        radial-gradient(1200px 600px at 90% -20%, rgba(34, 211, 238, .22), transparent 60%),
        radial-gradient(900px 520px at -10% 120%, rgba(59, 130, 246, .16), transparent 55%),
        #081225;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 5;
      background: rgba(10, 22, 44, 0.9);
      backdrop-filter: blur(7px);
      border-bottom: 1px solid #294b7a;
    }
    .bar, main { max-width: 1180px; margin: 0 auto; padding-left: 22px; padding-right: 22px; }
    .bar { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    h1, h2 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 24px; }
    h2 { font-size: 18px; }
    .subtitle, .muted { color: #93c5fd; font-size: 13px; }
    .status { border: 1px solid #22d3ee; background: #082f49; color: #cffafe; border-radius: 999px; padding: 7px 12px; font-size: 13px; white-space: nowrap; }
    main { padding-top: 22px; padding-bottom: 36px; display: grid; gap: 16px; }
    .panel, .metric { background: rgba(15, 32, 58, .78); border: 1px solid #2f4f7f; border-radius: 12px; box-shadow: 0 16px 30px rgba(2, 6, 23, .22); }
    .panel { padding: 16px; }
    form { display: grid; grid-template-columns: minmax(120px, 160px) minmax(180px, 1fr) minmax(120px, 150px) minmax(130px, 150px) auto; gap: 12px; align-items: end; }
    label { display: grid; gap: 6px; color: #cbd5e1; font-size: 13px; font-weight: 650; }
    input, select { width: 100%; border: 1px solid #3d6094; border-radius: 8px; padding: 10px 11px; background: #081225; color: #f8fafc; font-size: 15px; }
    input:focus, select:focus { outline: 2px solid #22d3ee; border-color: #22d3ee; }
    button { border: 0; border-radius: 8px; min-width: 112px; padding: 11px 16px; background: linear-gradient(135deg, #22d3ee, #0ea5e9); color: #06243b; cursor: pointer; font-size: 15px; font-weight: 800; }
    button:disabled { background: #475569; color: #cbd5e1; cursor: wait; }
    .message { min-height: 22px; margin-top: 10px; color: #cbd5e1; font-size: 14px; }
    .error { color: #f87171; white-space: pre-wrap; }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .metric { padding: 14px; }
    .metric span { display: block; color: #94a3b8; font-size: 13px; }
    .metric strong { display: block; margin-top: 6px; font-size: 25px; }
    .content { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 16px; align-items: start; }
    .panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 10px; }
    svg { width: 100%; height: 720px; display: block; overflow: visible; }
    .axis { stroke: #475569; stroke-width: 1; }
    .grid-line { stroke: #334155; stroke-width: 1; }
    .score-line { fill: none; stroke: #38bdf8; stroke-width: 3; }
    .bar-volume { fill: #94a3b8; opacity: .72; }
    .point { fill: #38bdf8; stroke: #0f172a; stroke-width: 2; }
    .point-hit, .chart-hit { cursor: crosshair; }
    .point-hit { fill: transparent; stroke: transparent; }
    .zero { stroke: #f87171; stroke-dasharray: 4 4; stroke-width: 1; }
    .axis-label { fill: #94a3b8; font-size: 12px; }
    .bar-label { fill: #e5e7eb; font-size: 12px; font-weight: 700; }
    .chart-tooltip {
      position: fixed;
      z-index: 20;
      display: none;
      min-width: 180px;
      max-width: 260px;
      padding: 9px 10px;
      border: 1px solid #38bdf8;
      border-radius: 6px;
      background: rgba(15, 23, 42, .96);
      color: #e5e7eb;
      box-shadow: 0 12px 26px rgba(2, 6, 23, .35);
      font-size: 12px;
      line-height: 1.45;
      pointer-events: none;
      white-space: pre-line;
    }
    .area-positive { fill: #22c55e; opacity: .35; stroke: #4ade80; stroke-width: 2; }
    .area-neutral { fill: #64748b; opacity: .58; stroke: #94a3b8; stroke-width: 2; }
    .area-negative { fill: #ef4444; opacity: .18; stroke: #f87171; stroke-width: 2; }
    .news-list { display: grid; gap: 10px; }
    .news-item { border: 1px solid #2f4f7f; border-radius: 10px; padding: 12px; background: rgba(8, 18, 37, .88); }
    .news-item a { display: block; color: #7dd3fc; font-weight: 700; text-decoration: none; line-height: 1.45; }
    .news-item a:hover { text-decoration: underline; }
    .news-meta { margin-top: 7px; color: #94a3b8; font-size: 12px; line-height: 1.45; }
    .positive { color: #4ade80; }
    .neutral { color: #94a3b8; }
    .negative { color: #f87171; }
    @media (max-width: 920px) {
      form, .content { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .status { display: none; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div>
        <h1>StockSense 股票預測</h1>
        <div class="subtitle">News + Sentiment + Time Series</div>
      </div>
      <div class="status" id="updatedAt">等待搜尋</div>
    </div>
  </header>

  <main>
    <section class="panel">
      <form id="searchForm">
        <label>股票代碼
          <input id="ticker" name="ticker" value="2330" placeholder="例如 2330 或 AAPL" autocomplete="off">
        </label>
        <label>關鍵字
          <input id="query" name="query" value="台積電 AI" placeholder="例如 台積電 AI" autocomplete="off">
        </label>
        <label>文章數量
          <input id="maxArticles" name="max_articles" type="number" min="10" max="100" value="100">
        </label>
        <label>情緒模型
          <select id="modelType" name="model_type">
            <option value="lexicon" selected>詞彙分析</option>
          </select>
        </label>
        <button id="searchButton" type="submit">搜尋</button>
      </form>
      <div class="message" id="message">輸入條件後按搜尋，系統會自動抓取最多 100 篇新聞並執行情緒分析與特徵聚合。</div>
    </section>

    <section class="stats" aria-label="搜尋統計">
      <div class="metric"><span>文章數量</span><strong id="articleCount">0</strong></div>
      <div class="metric"><span>平均情緒</span><strong id="avgScore">0.000</strong></div>
      <div class="metric"><span>正面比例</span><strong id="positiveRate">0%</strong></div>
      <div class="metric"><span>負面比例</span><strong id="negativeRate">0%</strong></div>
    </section>

    <section class="content">
      <section class="panel">
        <div class="panel-head">
          <h2>情緒圖表</h2>
          <span class="muted">資料來源：data/features/sentiment_features_hour.csv</span>
        </div>
        <svg id="chart" role="img" aria-label="文章情緒圖表"></svg>
        <div id="chartTooltip" class="chart-tooltip" role="status" aria-live="polite"></div>
      </section>

      <aside class="panel">
        <div class="panel-head">
          <h2>文章連結</h2>
          <span class="muted" id="newsCount">0 篇</span>
        </div>
        <div class="news-list" id="newsList"></div>
      </aside>
    </section>
  </main>

  <script>
    const form = document.getElementById("searchForm");
    const button = document.getElementById("searchButton");
    const message = document.getElementById("message");
    const chart = document.getElementById("chart");
    const chartTooltip = document.getElementById("chartTooltip");

    function pct(value) { return `${Math.round((value || 0) * 100)}%`; }
    function fmtTime(value) {
      if (!value) return "未知時間";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-TW", {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
      });
    }
    function totalArticlesInFeatures(rows) {
      return rows.reduce((total, row) => total + Number(row.news_count || 0), 0);
    }
    function tooltipText(row) {
      return [
        row.bucket_start || "未知時間",
        `新聞數量: ${Number(row.news_count || 0)}`,
        `平均情緒: ${Number(row.score_mean || 0).toFixed(3)}`,
        `正面: ${pct(row.positive_ratio)}`,
        `中立: ${pct(row.neutral_ratio)}`,
        `負面: ${pct(row.negative_ratio)}`
      ].join(String.fromCharCode(10));
    }
    function showChartTooltip(event, row) {
      chartTooltip.textContent = tooltipText(row);
      chartTooltip.style.display = "block";
      const offset = 14;
      const tooltipBox = chartTooltip.getBoundingClientRect();
      let left = event.clientX + offset;
      let top = event.clientY + offset;
      if (left + tooltipBox.width > window.innerWidth - 8) {
        left = event.clientX - tooltipBox.width - offset;
      }
      if (top + tooltipBox.height > window.innerHeight - 8) {
        top = event.clientY - tooltipBox.height - offset;
      }
      chartTooltip.style.left = `${Math.max(8, left)}px`;
      chartTooltip.style.top = `${Math.max(8, top)}px`;
    }
    function hideChartTooltip() {
      chartTooltip.style.display = "none";
    }
    function bindTooltip(el, row) {
      el.addEventListener("mouseenter", event => showChartTooltip(event, row));
      el.addEventListener("mousemove", event => showChartTooltip(event, row));
      el.addEventListener("mouseleave", hideChartTooltip);
    }
    function setStats(summary, rows = []) {
      const featureArticleCount = totalArticlesInFeatures(rows);
      document.getElementById("articleCount").textContent = featureArticleCount || summary.records || 0;
      document.getElementById("avgScore").textContent = Number(summary.score_mean || 0).toFixed(3);
      document.getElementById("positiveRate").textContent = pct(summary.positive_ratio);
      document.getElementById("negativeRate").textContent = pct(summary.negative_ratio);
      document.getElementById("newsCount").textContent = `${summary.records || 0} 篇`;
      document.getElementById("updatedAt").textContent = summary.generated_at ? `更新 ${summary.generated_at}` : "已更新";
      if (summary.search_query) {
        const model = summary.model_used || summary.model_type || "unknown";
        message.textContent = `完成：使用「${summary.search_query}」搜尋，要求 ${summary.requested_articles || 0} 篇，找到 ${summary.records || 0} 篇文章，${summary.feature_rows || 0} 個時間區間，模型 ${model}。`;
      }
    }
    function svgEl(name, attrs = {}) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", name);
      Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
      return el;
    }
    function drawChart(rows) {
      chart.replaceChildren();
      const box = chart.getBoundingClientRect();
      const width = Math.max(320, box.width || 740);
      const height = 720;
      const pad = { left: 52, right: 18, top: 50, bottom: 48 };
      const innerW = width - pad.left - pad.right;
      chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
      if (!rows.length) {
        hideChartTooltip();
        const text = svgEl("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "axis-label" });
        text.textContent = "尚無資料";
        chart.append(text);
        return;
      }
      const panelGap = 54;
      const panelH = (height - pad.top - pad.bottom - panelGap * 2) / 3;
      const panelTops = [pad.top, pad.top + panelH + panelGap, pad.top + (panelH + panelGap) * 2];
      const x = index => pad.left + (rows.length === 1 ? innerW / 2 : index * innerW / (rows.length - 1));
      const dateLabel = row => (row.bucket_start || "").slice(5, 10).replace("-", "/") || "未知";
      const legend = [["#ef4444", "負面"], ["#94a3b8", "中立"], ["#22c55e", "正面"], ["#64748b", "新聞數量"], ["#2563eb", "平均情緒"]];
      const legendStart = Math.max(pad.left, width - 470);
      legend.forEach(([color, label], index) => {
        const gx = legendStart + index * 88;
        chart.append(svgEl("line", { x1: gx, x2: gx + 28, y1: 18, y2: 18, stroke: color, "stroke-width": 4 }));
        const text = svgEl("text", { x: gx + 34, y: 22, class: "axis-label" });
        text.textContent = label;
        chart.append(text);
      });
      function drawPanelAxes(top, minY, maxY, labels) {
        for (let i = 0; i <= 4; i += 1) {
          const yy = top + i * panelH / 4;
          chart.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: yy, y2: yy, class: "grid-line" }));
          const label = svgEl("text", { x: 8, y: yy + 4, class: "axis-label" });
          label.textContent = labels[i] || "";
          chart.append(label);
        }
        chart.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: top + panelH, y2: top + panelH, class: "axis" }));
        chart.append(svgEl("line", { x1: pad.left, x2: pad.left, y1: top, y2: top + panelH, class: "axis" }));
        return value => top + (maxY - value) * panelH / (maxY - minY);
      }
      const yScore = drawPanelAxes(panelTops[0], -1, 1, ["1", "0.5", "0", "-0.5", "-1"]);
      chart.append(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: yScore(0), y2: yScore(0), class: "zero" }));
      chart.append(svgEl("polyline", { points: rows.map((row, index) => `${x(index)},${yScore(row.score_mean)}`).join(" "), class: "score-line" }));
      rows.forEach((row, index) => {
        const group = svgEl("g");
        const point = svgEl("circle", { cx: x(index), cy: yScore(row.score_mean), r: 5, class: "point" });
        const pointHit = svgEl("circle", { cx: x(index), cy: yScore(row.score_mean), r: 13, class: "point-hit" });
        bindTooltip(point, row);
        bindTooltip(pointHit, row);
        group.append(point);
        group.append(pointHit);
        chart.append(group);
      });
      const maxCount = Math.max(...rows.map(row => Number(row.news_count || 0)), 1);
      const countTicks = maxCount <= 1
        ? ["1", "", "", "", "0"]
        : [String(maxCount), "", String(Math.ceil(maxCount / 2)), "", "0"];
      const yCount = drawPanelAxes(panelTops[1], 0, maxCount, countTicks);
      rows.forEach((row, index) => {
        const barWidth = Math.max(6, innerW / Math.max(1, rows.length) * 0.28);
        const bar = svgEl("rect", { x: x(index) - barWidth / 2, y: yCount(row.news_count), width: barWidth, height: panelTops[1] + panelH - yCount(row.news_count), class: "bar-volume", rx: 2 });
        bindTooltip(bar, row);
        chart.append(bar);
        const countLabel = svgEl("text", { x: x(index), y: Math.max(panelTops[1] + 14, yCount(row.news_count) - 7), class: "bar-label", "text-anchor": "middle" });
        countLabel.textContent = row.news_count;
        chart.append(countLabel);
      });
      const yRatio = drawPanelAxes(panelTops[2], 0, 1, ["100%", "75%", "50%", "25%", "0%"]);
      function areaPath(valueOf) {
        const upper = rows.map((row, index) => `${x(index)},${yRatio(valueOf(row))}`).join(" L ");
        const lower = rows.slice().reverse().map((row, reverseIndex) => {
          const index = rows.length - 1 - reverseIndex;
          return `${x(index)},${yRatio(0)}`;
        }).join(" L ");
        return `M ${upper} L ${lower} Z`;
      }
      chart.append(svgEl("path", { d: areaPath(row => row.negative_ratio), class: "area-negative" }));
      chart.append(svgEl("path", { d: areaPath(row => row.neutral_ratio + row.positive_ratio), class: "area-neutral" }));
      chart.append(svgEl("path", { d: areaPath(row => row.positive_ratio), class: "area-positive" }));
      rows.forEach((row, index) => {
        if (index === 0 || index === rows.length - 1 || index % 2 === 0) {
          const label = svgEl("text", { x: x(index), y: height - 18, class: "axis-label", "text-anchor": "middle" });
          label.textContent = dateLabel(row);
          chart.append(label);
        }
      });
      rows.forEach((row, index) => {
        const left = index === 0 ? pad.left : (x(index - 1) + x(index)) / 2;
        const right = index === rows.length - 1 ? width - pad.right : (x(index) + x(index + 1)) / 2;
        const hit = svgEl("rect", {
          x: left,
          y: pad.top,
          width: Math.max(1, right - left),
          height: height - pad.top - pad.bottom,
          fill: "transparent",
          class: "chart-hit"
        });
        bindTooltip(hit, row);
        chart.append(hit);
      });
    }
    function renderNews(items) {
      const list = document.getElementById("newsList");
      list.replaceChildren();
      for (const item of items) {
        const article = document.createElement("article");
        article.className = "news-item";
        const labelMap = { positive: "正面", neutral: "中立", negative: "負面" };
        article.innerHTML = `
          <a href="${item.url || "#"}" target="_blank" rel="noreferrer">${item.headline || "無標題"}</a>
          <div class="news-meta">${item.source || "unknown"} · ${fmtTime(item.published_at || item.fetched_at)} · <strong class="${item.sentiment_label || "neutral"}">${labelMap[item.sentiment_label] || "中立"}</strong> (${Number(item.sentiment_score || 0).toFixed(3)})</div>
        `;
        list.append(article);
      }
    }
    async function search(event) {
      event.preventDefault();
      button.disabled = true;
      message.className = "message";
      message.textContent = "正在執行原始 pipeline，第一次可能需要一點時間...";
      try {
        const params = new URLSearchParams(new FormData(form));
        params.set("_", Date.now().toString());
        const response = await fetch(`/api/search?${params.toString()}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "搜尋失敗");
        setStats(payload.summary, payload.features);
        drawChart(payload.features);
        renderNews(payload.news);
        const model = payload.summary.model_used || payload.summary.model_type || "unknown";
        message.textContent = `完成：使用「${payload.summary.search_query || ""}」搜尋，要求 ${payload.summary.requested_articles || 0} 篇，找到 ${payload.summary.records} 篇文章，${payload.features.length} 個時間區間，模型 ${model}。`;
      } catch (error) {
        message.className = "message error";
        message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    }
    async function loadExistingData() {
      try {
        const response = await fetch(`/api/data?_=${Date.now()}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || "讀取既有資料失敗");
        setStats(payload.summary, payload.features);
        drawChart(payload.features);
        renderNews(payload.news);
        if (payload.summary.records) {
          message.textContent = `已載入既有資料：${payload.summary.records} 篇文章，${payload.features.length} 個時間區間。`;
        }
      } catch (error) {
        message.className = "message error";
        message.textContent = error.message;
      }
    }
    form.addEventListener("submit", search);
    loadExistingData();
  </script>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, payload: str) -> None:
    body = payload.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def run_command(args: list[str]) -> dict:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=240,
    )
    return {
        "args": args,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit and len(rows) >= limit:
                break
    return rows


def read_features(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    numeric_fields = [
        "news_count",
        "score_mean",
        "score_std",
        "score_min",
        "score_max",
        "positive_ratio",
        "neutral_ratio",
        "negative_ratio",
    ]
    for row in rows:
        for field in numeric_fields:
            try:
                value = float(row.get(field, 0) or 0)
                row[field] = int(value) if field == "news_count" else value
            except ValueError:
                row[field] = 0
    return rows


def write_runtime_config(search_query: str, max_articles: int) -> Path:
    source = {
        "name": "google_news_current_search",
        "type": "rss",
        "enabled": True,
        "list_url": (
            "https://news.google.com/rss/search?q="
            + quote(search_query)
            + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "language": "zh-TW",
        "timezone": "Asia/Taipei",
        "max_items": max_articles,
        "timeout_seconds": 20,
        "retry_count": 2,
        "rate_limit_seconds": 0.05,
        "rss_use_article_content": False,
    }
    RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_CONFIG.write_text(json.dumps({"sources": [source]}, ensure_ascii=False, indent=2), encoding="utf-8")
    return RUNTIME_CONFIG


def parse_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def record_id(url: str, headline: str, published_at: str | None) -> str:
    key = f"{url}|{headline}|{published_at or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def write_google_news_fallback(ticker: str, query: str, max_articles: int) -> int:
    search_text = " ".join(part for part in [ticker, query] if part).strip() or ticker or query
    url = (
        "https://news.google.com/rss/search?q="
        + quote(search_text)
        + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())

    records = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for item in root.findall("./channel/item")[:max_articles]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = item.findtext("source") or "google_news_fallback"
        published_at = parse_rss_datetime(item.findtext("pubDate"))
        if not title or not link:
            continue
        records.append(
            {
                "id": record_id(link, title, published_at),
                "source": source,
                "headline": title,
                "content": title,
                "url": link,
                "published_at": published_at,
                "fetched_at": fetched_at,
                "language": "zh-TW",
                "ticker": ticker,
                "sentiment_score": None,
                "sentiment_label": None,
            }
        )

    RAW_NEWS.parent.mkdir(parents=True, exist_ok=True)
    with RAW_NEWS.open("w", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    RAW_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    RAW_SUMMARY.write_text(
        json.dumps(
            {
                "output": str(RAW_NEWS.relative_to(ROOT)),
                "records_written": len(records),
                "runtime": {
                    "ticker": ticker,
                    "query": query,
                    "fallback": "google_news_rss",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(records)


def summarize(news: list[dict], features: list[dict]) -> dict:
    records = len(news)
    scores = []
    labels = {"positive": 0, "neutral": 0, "negative": 0}
    for item in news:
        try:
            scores.append(float(item.get("sentiment_score") or 0))
        except ValueError:
            scores.append(0)
        label = str(item.get("sentiment_label") or "neutral")
        labels[label if label in labels else "neutral"] += 1
    denominator = max(1, records)
    return {
        "records": records,
        "feature_rows": len(features),
        "score_mean": sum(scores) / denominator if scores else 0,
        "positive_ratio": labels["positive"] / denominator,
        "neutral_ratio": labels["neutral"] / denominator,
        "negative_ratio": labels["negative"] / denominator,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def reset_pipeline_outputs() -> None:
    empty_files = [RAW_NEWS, NORMALIZED_NEWS, FEATURES]
    empty_json_files = [RAW_SUMMARY, NORMALIZED_SUMMARY]
    for path in empty_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for path in empty_json_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")


def _build_sentiment_command(model_type: str) -> list[str]:
    return [
        sys.executable,
        "models/run_sentiment_batch.py",
        "--input",
        str(RAW_NEWS.relative_to(ROOT)),
        "--output",
        str(NORMALIZED_NEWS.relative_to(ROOT)),
        "--summary-output",
        str(NORMALIZED_SUMMARY.relative_to(ROOT)),
        "--workers",
        "4",
        "--model-type",
        "lexicon",
    ]


def run_pipeline(ticker: str, query: str, max_articles: int, model_type: str) -> dict:
    max_articles = min(100, max(10, max_articles))
    model_type = "lexicon"
    per_source = max_articles
    search_query = " ".join(part for part in [ticker, query] if part).strip() or query or ticker
    reset_pipeline_outputs()
    config = write_runtime_config(search_query=search_query, max_articles=max_articles)
    commands = [
        [
            sys.executable,
            "-m",
            "crawler.news_scraper",
            "--config",
            str(config.relative_to(ROOT)),
            "--output",
            str(RAW_NEWS.relative_to(ROOT)),
            "--summary-output",
            str(RAW_SUMMARY.relative_to(ROOT)),
            "--max-articles",
            str(max_articles),
            "--per-source-max-items",
            str(per_source),
            "--ticker",
            ticker,
            "--query",
            search_query,
            "--min-content-length",
            "1",
        ],
    ]
    logs = []
    for command in commands:
        result = run_command(command)
        logs.append(result)
        if result["returncode"] != 0:
            raise RuntimeError(
                "原始 crawler 執行失敗\n\n"
                f"指令: {' '.join(command)}\n\n"
                f"輸出:\n{result['stdout']}\n\n"
                f"錯誤:\n{result['stderr']}"
            )

    raw_news = read_jsonl(RAW_NEWS)
    if not raw_news:
        fallback_count = write_google_news_fallback(ticker=ticker, query=search_query, max_articles=max_articles)
        logs.append(
            {
                "args": ["google_news_fallback", search_query],
                "returncode": 0,
                "stdout": f"records_written={fallback_count}",
                "stderr": "",
            }
        )

    commands = [
        _build_sentiment_command(model_type),
        [
            sys.executable,
            "models/build_daily_features.py",
            "--input",
            str(NORMALIZED_NEWS.relative_to(ROOT)),
            "--output",
            str(FEATURES.relative_to(ROOT)),
            "--timeframe",
            "hour",
            "--timezone",
            "Asia/Taipei",
        ],
    ]
    for command in commands:
        result = run_command(command)
        logs.append(result)
        if result["returncode"] != 0:
            raise RuntimeError(
                "Pipeline 執行失敗\n\n"
                f"指令: {' '.join(command)}\n\n"
                f"輸出:\n{result['stdout']}\n\n"
                f"錯誤:\n{result['stderr']}"
            )
    news = read_jsonl(NORMALIZED_NEWS, limit=200)
    features = read_features(FEATURES)
    summary = summarize(news, features)
    summary.update(
        {
            "ticker": ticker,
            "query": query,
            "search_query": search_query,
            "requested_articles": max_articles,
            "model_type": "lexicon",
        }
    )
    return {
        "ok": True,
        "summary": summary,
        "features": features,
        "news": news,
        "logs": logs,
    }


def load_existing_payload() -> dict:
    news = read_jsonl(NORMALIZED_NEWS, limit=200)
    features = read_features(FEATURES)
    summary = summarize(news, features)
    return {
        "ok": True,
        "summary": summary,
        "features": features,
        "news": news,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            text_response(self, HTML)
            return
        if parsed.path == "/api/data":
            json_response(self, load_existing_payload())
            return
        if parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            ticker = (params.get("ticker", ["2330"])[0] or "2330").strip()
            query = (params.get("query", [""])[0] or ticker).strip()
            model_type = (params.get("model_type", ["lexicon"])[0] or "lexicon").strip().lower()
            try:
                max_articles = int(params.get("max_articles", ["100"])[0])
            except ValueError:
                max_articles = 100
            try:
                json_response(
                    self,
                    run_pipeline(
                        ticker=ticker,
                        query=query,
                        max_articles=max_articles,
                        model_type=model_type,
                    ),
                )
            except Exception as exc:
                json_response(self, {"ok": False, "error": f"{exc}\n\n{traceback.format_exc()}"}, status=500)
            return
        json_response(self, {"ok": False, "error": "Not found"}, status=404)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Open http://127.0.0.1:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
