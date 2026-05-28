# Cron Templates

以下樣板採用 macOS/Linux crontab 格式，可依環境調整。

## 1) 每日離線重訓 + 自動回滾判斷 + promote

```cron
# 每天 02:30 執行，訓練後若指標變差自動回滾，並寫入事件 log + webhook 告警
30 2 * * * cd /Users/peterchiu/stock_predict && /Users/peterchiu/stock_predict/.venv/bin/python models/retrain_rnn_and_promote.py --input data/normalized/news_with_sentiment.jsonl --registry-dir models/rnn_registry --eval-input data/normalized/news_with_sentiment.jsonl --eval-label-source field --rollback-metric macro_f1 --rollback-min-improvement 0.002 --epochs 8 --batch-size 64 --event-log models/rnn_registry/events.log --notify-on rollback --notify-hook-url "https://your-hook-endpoint" --summary-output models/rnn_registry/last_retrain_summary.json >> logs/retrain_rnn.log 2>&1
```

## 2) 每 5 分鐘線上 A/B 推論（lexicon vs RNN）

```cron
# 每 5 分鐘跑一次 A/B 流量切分
*/5 * * * * cd /Users/peterchiu/stock_predict && /Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py --input data/raw/news_latest.jsonl --output data/normalized/news_with_sentiment_ab.jsonl --summary-output data/monitoring/ab_runs/summary_$(date +\%Y\%m\%d_\%H\%M\%S).json --ab-enabled --ab-rnn-ratio 0.35 --ab-key-field id --ab-salt stock_predict_ab_v1 --rnn-model-dir models/rnn_registry --rnn-batch-size 128 --workers 4 --ab-report-output data/monitoring/ab_runs/report_$(date +\%Y\%m\%d_\%H\%M\%S).json >> logs/ab_inference.log 2>&1
```

## 3) 每日彙總 A/B 監控報表

```cron
# 每天 03:10 產出前一輪累積報表 + 7/30 日趨勢圖 + 自適應 ratio（寫回策略檔）
10 3 * * * cd /Users/peterchiu/stock_predict && /Users/peterchiu/stock_predict/.venv/bin/python models/generate_ab_monitoring_report.py --input-glob "data/monitoring/ab_runs/report_*.json" --eval-summary models/rnn_registry/last_retrain_summary.json --output data/monitoring/ab_report_daily.json --markdown-output data/monitoring/ab_report_daily.md --ratio-config models/rnn_registry/traffic_policy.json --weight-accuracy 0.75 --weight-throughput 0.25 --max-ratio-step 0.08 --write-ratio-config >> logs/ab_report.log 2>&1
```

## 4) 可選：低流量時段把 RNN 比例拉高

```cron
# 盤後測試提高 RNN 比例
30 20 * * 1-5 cd /Users/peterchiu/stock_predict && /Users/peterchiu/stock_predict/.venv/bin/python models/run_sentiment_batch.py --input data/raw/news_latest.jsonl --output data/normalized/news_with_sentiment_ab_offpeak.jsonl --summary-output data/monitoring/ab_runs/offpeak_summary_$(date +\%Y\%m\%d).json --ab-enabled --ab-rnn-ratio 0.6 --ab-key-field id --ab-salt stock_predict_ab_v1 --rnn-model-dir models/rnn_registry --rnn-batch-size 256 --workers 4 --ab-report-output data/monitoring/ab_runs/offpeak_report_$(date +\%Y\%m\%d).json >> logs/ab_offpeak.log 2>&1
```
