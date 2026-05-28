## Plan: 邱彥嘉分階段交付計畫


**Steps**
1. Phase 0: 資料契約先定義（阻塞後續全部）
2. 定義統一新聞 schema（headline、content、published_at、source、url、ticker、fetched_at、sentiment_score、sentiment_label）與去重鍵（url hash + title + published_at）。
3. 固定第一版市場為台股，挑 2-3 個可合法抓取來源，明確頻率與備援策略。
4. Phase 1: 爬蟲 MVP
5. 建立來源設定規格（list_url、selector 群組、timezone、rate_limit、enabled）。
6. 實作清單頁→文章頁→正規化→去重→落盤流程，加入 timeout/retry/backoff 與錯誤分類。
7. 加入品質門檻檢查（解析成功率、空內容率、重複率）。
8. 交付門檻：每日至少 200 篇結構化新聞，連續 3 天排程成功。
9. Phase 2: 情緒快線（先快）
10. 先接預訓練情緒模型作 baseline，輸出 score + label。
11. 建立人工抽樣回饋池（每日 50-100 筆）累積訓練資料。
12. 產出交易日層級情緒特徵表（均值、極性比例、波動度、消息量）。
13. Phase 3: RNN/LSTM 主線（後穩）
14. 定義任務與指標（三分類 F1 或回歸 MAE），採時間切分防資料洩漏。
15. 建立可重現訓練流程（checkpoint、早停、版本標記）。
16. 比較 baseline 與 RNN；若 RNN 優勢不穩定，保留 baseline 做 fallback。
17. Phase 4: 產品化與監控
18. 串接排程：抓取、推論、聚合、報告全自動。
19. 建立監控：抓取成功率、延遲、資料漂移、情緒分布漂移、日產量與異常告警。
20. 建立補抓機制（指定日期區間回補，避免資料斷層）。
21. Phase 5: 驗收與交接
22. 完成操作手冊、故障排除與模型版本紀錄。
23. 以 1-2 檔台股標的完成 demo 流程驗收。

**Relevant files**
- news_scraper.py - 爬蟲主流程、錯誤處理、輸出落盤
- news_sources.json - 來源設定 schema 與 selector 規格
- requirements.txt - 爬蟲/NLP/訓練/監控依賴定義
- README.zh-TW.md - 中文安裝、執行、排程與驗收說明
- README.md - 英文版同步文件
- .gitignore - 快取、模型檔與產物忽略規則
- .github - CI 與排程 workflow 入口

**Verification**
1. 爬蟲連跑 3 天，確認成功率、解析率、去重率、日產量達標。
2. 抽樣核對 schema 完整率與時間欄位正規化正確。
3. baseline 與 RNN 在固定測試切分比較並留存指標報告。
4. 全流程一鍵重跑，失敗後可恢復且結果可重現。
5. 連續 7 天排程成功並可產出每日健康報告。

**Decisions**
- 交付等級：接近產品版
- 模型策略：兩者都做（先預訓練 baseline，再上 RNN/LSTM）
- 市場範圍：第一版先台股
- 產量目標：每日 200 篇結構化新聞
- 時程：2 週以上，建議 3-5 週