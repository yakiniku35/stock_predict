const rootNode = document.getElementById('rechartsChartRoot');
const React = window.React;
const ReactDOM = window.ReactDOM;
const Recharts = window.Recharts;

if (!rootNode) {
  console.warn('[Recharts] rechartsChartRoot not found.');
} else if (!React || !ReactDOM || !Recharts) {
  rootNode.innerHTML = '<div style="height:420px;display:grid;place-items:center;color:#f87171;">Recharts 載入失敗，請重新整理頁面。</div>';
  console.error('[Recharts] Missing dependency', {
    hasReact: !!React,
    hasReactDOM: !!ReactDOM,
    hasRecharts: !!Recharts,
  });
} else {
const { useState, useEffect, useMemo, useCallback } = React;
const {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} = Recharts;

const TIME_RANGES = [
  { label: '5D', days: 5, defaultInterval: '15m' },
  { label: '1M', days: 30, defaultInterval: '60m' },
  { label: '3M', days: 90, defaultInterval: '1d' },
  { label: '6M', days: 180, defaultInterval: '1d' },
  { label: '1Y', days: 365, defaultInterval: '1d' },
  { label: '2Y', days: 730, defaultInterval: '1wk' },
  { label: '3Y', days: 1095, defaultInterval: '1wk' },
  { label: 'ALL', days: 3650, defaultInterval: '1mo' },
];

const FREQ_OPTIONS = [
  { label: '5m', value: '5m', maxDays: 60 },
  { label: '15m', value: '15m', maxDays: 60 },
  { label: '1H', value: '60m', maxDays: 730 },
  { label: '1D', value: '1d', maxDays: 3650 },
  { label: '1W', value: '1wk', maxDays: 3650 },
  { label: '1M', value: '1mo', maxDays: 3650 },
];

const SUBCHART_MODE = 'multi';

function mapDaysToPeriod(days) {
  if (days <= 5) return '5d';
  if (days <= 30) return '1mo';
  if (days <= 90) return '3mo';
  if (days <= 180) return '6mo';
  if (days <= 365) return '1y';
  if (days <= 730) return '2y';
  if (days <= 1095) return '5y';
  if (days <= 3650) return '10y';
  return 'max';
}

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return Number(value).toFixed(digits);
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload;
  return (
    <div style={{ background: '#0b1220', border: '1px solid #334155', borderRadius: 8, padding: 10, color: '#e5e7eb' }}>
      <div style={{ marginBottom: 6, color: '#93c5fd', fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: 12 }}>開盤 {fmtNumber(row.open)}</div>
      <div style={{ fontSize: 12 }}>最高 {fmtNumber(row.high)}</div>
      <div style={{ fontSize: 12 }}>最低 {fmtNumber(row.low)}</div>
      <div style={{ fontSize: 12 }}>收盤 {fmtNumber(row.close)}</div>
      <div style={{ fontSize: 12 }}>量 {(Number(row.volume || 0) / 1e6).toFixed(2)}M</div>
    </div>
  );
}

function IndicatorToggle({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '6px 10px',
        borderRadius: 999,
        border: `1px solid ${active ? '#0ea5e9' : '#334155'}`,
        background: active ? '#082f49' : '#020617',
        color: active ? '#7dd3fc' : '#cbd5e1',
        fontSize: 12,
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  );
}

function StockRechartsPanel() {
  const [symbol, setSymbol] = useState('2330');
  const [days, setDays] = useState(365);
  const [interval, setInterval] = useState('1d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [rows, setRows] = useState([]);
  const [activeSubs, setActiveSubs] = useState(new Set());

  useEffect(() => {
    window.setRechartsSymbol = (nextSymbol) => {
      if (!nextSymbol) return;
      setSymbol(String(nextSymbol).toUpperCase());
    };
    return () => {
      delete window.setRechartsSymbol;
    };
  }, []);

  const isFreqValid = useCallback((maxDays) => days <= maxDays, [days]);

  const handleRangeChange = useCallback((range) => {
    setDays(range.days);
    setInterval((current) => {
      const target = range.defaultInterval;
      const fallback = FREQ_OPTIONS.find((f) => f.maxDays >= range.days);
      if (target && (FREQ_OPTIONS.find((f) => f.value === target)?.maxDays || 0) >= range.days) {
        return target;
      }
      if (fallback) return fallback.value;
      return current;
    });
  }, []);

  const toggleSub = useCallback((name) => {
    setActiveSubs((prev) => {
      const next = new Set(prev);
      if (SUBCHART_MODE === 'single') {
        if (next.has(name) && next.size === 1) {
          next.clear();
        } else {
          next.clear();
          next.add(name);
        }
        return next;
      }
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');

    const period = mapDaysToPeriod(days);
    fetch(`/api/stock_insight?ticker=${encodeURIComponent(symbol)}&period=${period}&interval=${interval}`)
      .then((res) => {
        if (!res.ok) throw new Error('無法取得股價資料');
        return res.json();
      })
      .then((json) => {
        if (!alive) return;
        const base = Array.isArray(json.stock_price_trends) ? json.stock_price_trends : [];
        const indicators = json.technical_indicators || {};

        const formatted = base.map((d, i) => ({
          date: new Date(d.date).toLocaleDateString(),
          open: Number(d.open),
          high: Number(d.high),
          low: Number(d.low),
          close: Number(d.close),
          volume: Number(d.volume || 0),
          fill: Number(d.close) >= Number(d.open) ? '#22c55e' : '#ef4444',
          sma5: indicators?.sma?.sma5?.[i] ?? null,
          sma20: indicators?.sma?.sma20?.[i] ?? null,
          sma60: indicators?.sma?.sma60?.[i] ?? null,
          bbUpper: indicators?.bb?.upper?.[i] ?? null,
          bbLower: indicators?.bb?.lower?.[i] ?? null,
          macd: indicators?.macd?.macd?.[i] ?? null,
          macdSignal: indicators?.macd?.signal?.[i] ?? null,
          macdHist: indicators?.macd?.histogram?.[i] ?? null,
          rsi: indicators?.rsi?.[i] ?? null,
          kdK: indicators?.kd?.k?.[i] ?? null,
          kdD: indicators?.kd?.d?.[i] ?? null,
          bias: indicators?.bias?.[i] ?? null,
          ad: indicators?.ad?.[i] ?? null,
        }));

        setRows(formatted);
      })
      .catch((err) => {
        if (!alive) return;
        setError(err?.message || '讀取失敗');
        setRows([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [symbol, days, interval]);

  const latest = useMemo(() => (rows.length ? rows[rows.length - 1] : null), [rows]);

  return (
    <div>
      <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {TIME_RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => handleRangeChange(r)}
              style={{
                padding: '6px 10px',
                borderRadius: 8,
                border: `1px solid ${days === r.days ? '#2563eb' : '#334155'}`,
                background: days === r.days ? '#2563eb' : '#111827',
                color: days === r.days ? '#fff' : '#cbd5e1',
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {r.label}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>FREQ</span>
          {FREQ_OPTIONS.map((f) => {
            const valid = isFreqValid(f.maxDays);
            return (
              <button
                key={f.value}
                type="button"
                disabled={!valid}
                onClick={() => valid && setInterval(f.value)}
                style={{
                  padding: '6px 10px',
                  borderRadius: 8,
                  border: `1px solid ${interval === f.value ? '#4f46e5' : '#334155'}`,
                  background: interval === f.value ? '#4f46e5' : '#111827',
                  color: valid ? (interval === f.value ? '#fff' : '#cbd5e1') : '#6b7280',
                  cursor: valid ? 'pointer' : 'not-allowed',
                  opacity: valid ? 1 : 0.45,
                  fontSize: 12,
                }}
              >
                {f.label}
              </button>
            );
          })}
          {latest ? (
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#93c5fd' }}>
              {symbol} Close {fmtNumber(latest.close)}
            </span>
          ) : null}
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <IndicatorToggle active={activeSubs.has('macd')} onClick={() => toggleSub('macd')}>MACD</IndicatorToggle>
          <IndicatorToggle active={activeSubs.has('rsi')} onClick={() => toggleSub('rsi')}>RSI</IndicatorToggle>
          <IndicatorToggle active={activeSubs.has('kd')} onClick={() => toggleSub('kd')}>KD</IndicatorToggle>
          <IndicatorToggle active={activeSubs.has('bias')} onClick={() => toggleSub('bias')}>BIAS</IndicatorToggle>
          <IndicatorToggle active={activeSubs.has('ad')} onClick={() => toggleSub('ad')}>AD</IndicatorToggle>
        </div>
      </div>

      {loading ? (
        <div style={{ height: 420, display: 'grid', placeItems: 'center', color: '#94a3b8' }}>Loading...</div>
      ) : error ? (
        <div style={{ height: 420, display: 'grid', placeItems: 'center', color: '#f87171' }}>{error}</div>
      ) : (
        <>
          <div style={{ width: '100%', height: 420 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="date" minTickGap={28} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis yAxisId="price" domain={["auto", "auto"]} tick={{ fill: '#94a3b8', fontSize: 11 }} width={58} />
                <YAxis yAxisId="volume" orientation="right" tick={{ fill: '#64748b', fontSize: 11 }} width={50} tickFormatter={(v) => `${(v / 1e6).toFixed(0)}M`} />
                <Tooltip content={<CustomTooltip />} />
                <Legend wrapperStyle={{ color: '#cbd5e1', fontSize: 12 }} />

                <Bar yAxisId="volume" dataKey="volume" fill="#334155" opacity={0.35} name="Volume" />
                <Line yAxisId="price" dataKey="close" stroke="#22c55e" strokeWidth={2} dot={false} name="Close" />
                <Line yAxisId="price" dataKey="sma5" stroke="#0ea5e9" strokeWidth={1.2} dot={false} name="SMA5" />
                <Line yAxisId="price" dataKey="sma20" stroke="#f59e0b" strokeWidth={1.2} dot={false} name="SMA20" />
                <Line yAxisId="price" dataKey="sma60" stroke="#a78bfa" strokeWidth={1.1} dot={false} name="SMA60" />
                <Line yAxisId="price" dataKey="bbUpper" stroke="#94a3b8" strokeDasharray="4 4" strokeWidth={1} dot={false} name="BB Upper" />
                <Line yAxisId="price" dataKey="bbLower" stroke="#94a3b8" strokeDasharray="4 4" strokeWidth={1} dot={false} name="BB Lower" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {activeSubs.size > 0 ? (
            <div style={{ display: 'grid', gap: 10, marginTop: 10 }}>
              {Array.from(activeSubs).map((name) => (
                <div key={name} style={{ width: '100%', height: 220, border: '1px solid #1f2937', borderRadius: 8, padding: 6, background: '#020617' }}>
                  <ResponsiveContainer>
                    <ComposedChart data={rows} margin={{ top: 10, right: 16, left: 0, bottom: 2 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                      <XAxis dataKey="date" minTickGap={28} tick={{ fill: '#64748b', fontSize: 10 }} />
                      <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={56} />
                      <Tooltip content={<CustomTooltip />} />
                      <Legend wrapperStyle={{ color: '#cbd5e1', fontSize: 11 }} />

                      {name === 'macd' ? (
                        <>
                          <Bar dataKey="macdHist" fill="#334155" name="MACD Hist" />
                          <Line dataKey="macd" stroke="#0ea5e9" dot={false} strokeWidth={1.6} name="MACD" />
                          <Line dataKey="macdSignal" stroke="#f59e0b" dot={false} strokeWidth={1.5} name="Signal" />
                        </>
                      ) : null}

                      {name === 'rsi' ? (
                        <>
                          <Line dataKey="rsi" stroke="#a855f7" dot={false} strokeWidth={1.8} name="RSI" />
                          <Line dataKey={() => 70} stroke="#ef4444" dot={false} strokeDasharray="4 4" name="RSI 70" />
                          <Line dataKey={() => 30} stroke="#10b981" dot={false} strokeDasharray="4 4" name="RSI 30" />
                        </>
                      ) : null}

                      {name === 'kd' ? (
                        <>
                          <Line dataKey="kdK" stroke="#facc15" dot={false} strokeWidth={1.6} name="K" />
                          <Line dataKey="kdD" stroke="#a855f7" dot={false} strokeWidth={1.6} name="D" />
                        </>
                      ) : null}

                      {name === 'bias' ? (
                        <>
                          <Line dataKey="bias" stroke="#f97316" dot={false} strokeWidth={1.8} name="BIAS" />
                          <Line dataKey={() => 0} stroke="#64748b" dot={false} strokeDasharray="4 4" name="0%" />
                        </>
                      ) : null}

                      {name === 'ad' ? (
                        <Line dataKey={(d) => (d.ad == null ? null : d.ad / 1000000)} stroke="#22c55e" dot={false} strokeWidth={1.8} name="A/D (M)" />
                      ) : null}
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

if (rootNode) {
  const root = ReactDOM.createRoot(rootNode);
  root.render(<StockRechartsPanel />);
}
}
