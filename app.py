import os
import time
import sqlite3
from datetime import datetime, timezone

import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Multi-AI Crypto Bot V1.2", page_icon="📊", layout="wide")

APP_VERSION = "V1.2"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trades.db")
BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]

st.title("📊 Multi-AI Crypto Market Analysis Bot — V1.2")
st.caption("Public market data • Confirmed candles • Paper trading only")
st.warning("শিক্ষামূলক প্রোটোটাইপ। লাভ নিশ্চিত করে না। এখানে কোনো বাস্তব exchange order পাঠানো হয় না।")

# ---------------- SQLite storage ----------------
def db_connect():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_key TEXT UNIQUE NOT NULL,
            signal_time TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            sl REAL NOT NULL,
            tp1 REAL NOT NULL,
            tp2 REAL NOT NULL,
            virtual_size_usdt REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            tp1_hit INTEGER NOT NULL DEFAULT 0,
            tp1_time TEXT,
            exit_time TEXT,
            realized_pnl_usdt REAL,
            last_processed_close_time TEXT,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()


def get_trades():
    with db_connect() as conn:
        rows = conn.execute("SELECT * FROM paper_trades ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def insert_trade(t):
    with db_connect() as conn:
        conn.execute("""
        INSERT OR IGNORE INTO paper_trades
        (signal_key, signal_time, symbol, interval, side, entry, sl, tp1, tp2,
         virtual_size_usdt, status, tp1_hit, created_at, last_processed_close_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 0, ?, ?)
        """, (
            t["signal_key"], t["signal_time"], t["symbol"], t["interval"], t["side"],
            t["entry"], t["sl"], t["tp1"], t["tp2"], t["virtual_size_usdt"],
            t["created_at"], t["signal_time"]
        ))
        conn.commit()


def update_trade(trade_id, **fields):
    allowed = {"status", "tp1_hit", "tp1_time", "exit_time", "realized_pnl_usdt", "last_processed_close_time"}
    updates = [(k, v) for k, v in fields.items() if k in allowed]
    if not updates:
        return
    sql = ", ".join(f"{k} = ?" for k, _ in updates)
    vals = [v for _, v in updates] + [trade_id]
    with db_connect() as conn:
        conn.execute(f"UPDATE paper_trades SET {sql} WHERE id = ?", vals)
        conn.commit()


def clear_trades():
    with db_connect() as conn:
        conn.execute("DELETE FROM paper_trades")
        conn.commit()


init_db()

# ---------------- Settings ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    symbol = st.selectbox("Crypto pair", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"], index=0)
    interval = st.selectbox("Chart timeframe", ["5m", "15m", "1h"], index=0)
    refresh_seconds = st.slider("Refresh interval (seconds)", 30, 180, 60, 15)
    paper_size = st.number_input("Virtual position size (USDT)", min_value=10.0, max_value=100000.0, value=100.0, step=10.0)
    st.caption("Virtual position size হলো trade-এর notional value; বাস্তব টাকা নয়।")
    st.caption("SQLite history এই app runtime-এ থাকে; redeploy/runtime reset হলে ফাইল হারাতে পারে।")

# ---------------- Market data ----------------
@st.cache_data(ttl=20, show_spinner=False)
def get_klines(pair, timeframe, limit=250):
    last_error = None
    for base in BINANCE_BASES:
        try:
            r = requests.get(
                f"{base}/api/v3/klines",
                params={"symbol": pair, "interval": timeframe, "limit": limit},
                timeout=12,
            )
            r.raise_for_status()
            raw = r.json()
            cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
            frame = pd.DataFrame(raw, columns=cols)
            for c in ["open", "high", "low", "close", "volume"]:
                frame[c] = pd.to_numeric(frame[c], errors="coerce")
            frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
            frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
            return frame.dropna().reset_index(drop=True), None
        except Exception as e:
            last_error = str(e)
    return None, last_error or "Unknown market data error"


def indicators(frame):
    x = frame.copy()
    x["ema9"] = x["close"].ewm(span=9, adjust=False).mean()
    x["ema21"] = x["close"].ewm(span=21, adjust=False).mean()
    x["ema50"] = x["close"].ewm(span=50, adjust=False).mean()
    delta = x["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    x["rsi"] = (100 - (100 / (1 + rs))).fillna(50)
    ema12 = x["close"].ewm(span=12, adjust=False).mean()
    ema26 = x["close"].ewm(span=26, adjust=False).mean()
    x["macd"] = ema12 - ema26
    x["macd_signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    prev_close = x["close"].shift(1)
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    x["vol_avg20"] = x["volume"].rolling(20).mean()
    # Prior-candle structure levels: current candle is excluded.
    x["swing_high"] = x["high"].rolling(20).max().shift(1)
    x["swing_low"] = x["low"].rolling(20).min().shift(1)
    x["support20"] = x["low"].rolling(20).min().shift(1)
    x["resistance20"] = x["high"].rolling(20).max().shift(1)
    return x


df, data_error = get_klines(symbol, interval)
if df is None or len(df) < 80:
    st.error(f"লাইভ মার্কেট ডেটা পাওয়া যায়নি: {data_error or 'ডেটা অপর্যাপ্ত'}")
    st.info("কিছুক্ষণ পর Refresh করুন। নেটওয়ার্ক বা API সাময়িকভাবে বন্ধ থাকতে পারে।")
    st.stop()

# Binance's last kline may still be forming; use only completed candles for signals.
analysis = df.iloc[:-1].copy()
a = indicators(analysis).dropna().reset_index(drop=True)
if len(a) < 10:
    st.error("Indicator হিসাবের জন্য পর্যাপ্ত candle নেই।")
    st.stop()

last = a.iloc[-1]
price = float(last["close"])
atr = float(last["atr"])
if not np.isfinite(atr) or atr <= 0:
    st.error("ATR হিসাব করা যায়নি।")
    st.stop()

# Higher timeframe confirmation uses the last completed 15m candle.
htf_df, htf_error = get_klines(symbol, "15m", 150)
htf_up = htf_down = False
if htf_df is not None and len(htf_df) > 60:
    h = indicators(htf_df.iloc[:-1].copy()).dropna()
    if len(h):
        hlast = h.iloc[-1]
        htf_up = bool(hlast["close"] > hlast["ema21"] and hlast["ema21"] > hlast["ema50"])
        htf_down = bool(hlast["close"] < hlast["ema21"] and hlast["ema21"] < hlast["ema50"])

# ---------------- Ten directional checks ----------------
prior10 = analysis.iloc[-11:-1]
prior_low10 = float(prior10["low"].min())
prior_high10 = float(prior10["high"].max())

bull_structure = bool(price > float(last["swing_high"]))
bear_structure = bool(price < float(last["swing_low"]))
bull_momentum = bool(last["rsi"] >= 52 and last["macd"] > last["macd_signal"])
bear_momentum = bool(last["rsi"] <= 48 and last["macd"] < last["macd_signal"])
atr_pct = atr / price * 100
volatility_ok = bool(0.03 <= atr_pct <= 2.5)

# Sweep means price traded beyond a prior extreme and the candle closed back inside.
bull_liquidity = bool(float(last["low"]) < prior_low10 and price > prior_low10)
bear_liquidity = bool(float(last["high"]) > prior_high10 and price < prior_high10)

support = float(last["support20"])
resistance = float(last["resistance20"])
near_support = abs(price - support) <= max(atr * 0.8, price * 0.001)
near_resistance = abs(resistance - price) <= max(atr * 0.8, price * 0.001)
bull_sr = bool(near_support or bull_structure)
bear_sr = bool(near_resistance or bear_structure)

body = abs(float(last["close"]) - float(last["open"]))
candle_range = max(float(last["high"] - last["low"]), 1e-12)
lower_wick = min(float(last["open"]), float(last["close"])) - float(last["low"])
upper_wick = float(last["high"]) - max(float(last["open"]), float(last["close"]))
bull_candle = bool(
    (last["close"] > last["open"] and body / candle_range >= 0.45)
    or (lower_wick / candle_range >= 0.55 and last["close"] > last["open"])
)
bear_candle = bool(
    (last["close"] < last["open"] and body / candle_range >= 0.45)
    or (upper_wick / candle_range >= 0.55 and last["close"] < last["open"])
)
volume_ok = bool(pd.notna(last["vol_avg20"]) and last["volume"] >= last["vol_avg20"])
bull_indicators = bool(last["close"] > last["ema9"] > last["ema21"] and last["rsi"] > 50)
bear_indicators = bool(last["close"] < last["ema9"] < last["ema21"] and last["rsi"] < 50)
bull_tf = bool(htf_up and price > last["ema21"])
bear_tf = bool(htf_down and price < last["ema21"])

sl_distance = atr * 1.5
# Actual geometry check, not a tautology: TP2 must be at least 2R from entry.
rr_ok = bool(sl_distance > 0 and np.isclose((2 * sl_distance) / sl_distance, 2.0))

checks_buy = [
    ("Market Structure", bull_structure), ("Momentum", bull_momentum),
    ("Volatility", volatility_ok), ("Liquidity Sweep", bull_liquidity),
    ("Support / Resistance", bull_sr), ("Candle Pattern", bull_candle),
    ("Volume", volume_ok), ("Selected Indicators", bull_indicators),
    ("Timeframe Confirmation", bull_tf), ("Risk / Reward", rr_ok),
]
checks_sell = [
    ("Market Structure", bear_structure), ("Momentum", bear_momentum),
    ("Volatility", volatility_ok), ("Liquidity Sweep", bear_liquidity),
    ("Support / Resistance", bear_sr), ("Candle Pattern", bear_candle),
    ("Volume", volume_ok), ("Selected Indicators", bear_indicators),
    ("Timeframe Confirmation", bear_tf), ("Risk / Reward", rr_ok),
]

buy_score = sum(bool(v) for _, v in checks_buy)
sell_score = sum(bool(v) for _, v in checks_sell)
side = "BUY" if buy_score > sell_score else ("SELL" if sell_score > buy_score else "NEUTRAL")
score = max(buy_score, sell_score)
chosen_checks = checks_buy if side == "BUY" else checks_sell if side == "SELL" else checks_buy
chosen = dict(chosen_checks)

# Conservative rule: 8/10 plus key confirmation checks. This is a prototype rule,
# not a claim of profitability. Require momentum, volatility, indicators, candle,
# and at least one of structure/sweep. Higher-timeframe confirmation is shown but
# not mandatory, to avoid making all signals dependent on a second timeframe.
mandatory_ok = bool(
    chosen.get("Momentum", False)
    and chosen.get("Volatility", False)
    and chosen.get("Selected Indicators", False)
    and chosen.get("Candle Pattern", False)
    and (chosen.get("Market Structure", False) or chosen.get("Liquidity Sweep", False))
    and chosen.get("Risk / Reward", False)
)
confirmed = bool(side in ("BUY", "SELL") and score >= 8 and mandatory_ok)
warning = bool(side in ("BUY", "SELL") and not confirmed and score >= 6)

if side == "BUY":
    entry, sl, tp1, tp2 = price, price - sl_distance, price + sl_distance, price + 2 * sl_distance
elif side == "SELL":
    entry, sl, tp1, tp2 = price, price + sl_distance, price - sl_distance, price - 2 * sl_distance
else:
    entry = sl = tp1 = tp2 = None

# ---------------- UI ----------------
m1, m2, m3, m4 = st.columns(4)
m1.metric("Last closed price", f"{price:,.4f}")
m2.metric("RSI (14)", f"{float(last['rsi']):.1f}")
m3.metric("ATR (14)", f"{atr:,.4f}")
m4.metric("Volatility", f"{atr_pct:.3f}%")

st.subheader(f"{symbol} — {interval} chart")
fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=analysis["open_time"], open=analysis["open"], high=analysis["high"],
    low=analysis["low"], close=analysis["close"], name="Candles"
))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema9"], mode="lines", name="EMA 9"))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema21"], mode="lines", name="EMA 21"))
fig.add_trace(go.Scatter(x=a["open_time"], y=a["ema50"], mode="lines", name="EMA 50"))
if entry is not None:
    for y, label in [(entry, "Entry reference"), (sl, "Stop Loss"), (tp1, "TP1 (1R)"), (tp2, "TP2 (2R)")]:
        fig.add_hline(y=y, line_dash="dash", annotation_text=f"{label}: {y:,.4f}")
fig.update_layout(height=520, xaxis_rangeslider_visible=False, legend_orientation="h", margin=dict(l=10, r=10, t=35, b=10))
st.plotly_chart(fig, use_container_width=True)

left, right = st.columns([1, 1])
with left:
    st.subheader("Analysis progress")
    st.progress(score / 10, text=f"{side} checks: {score}/10 ({score * 10}%)")
    if confirmed:
        st.success(f"PAPER SETUP CONFIRMED: {side} — V1.2 rule পাস করেছে।")
    elif warning:
        st.warning(f"সম্ভাব্য {side} setup — এখনো V1.2 confirmation rule পাস করেনি।")
    else:
        st.info("NO CONFIRMED SETUP — অপেক্ষা করুন।")
    st.caption("স্কোর শর্ত-পাসের সংখ্যা; এটি win probability বা লাভের নিশ্চয়তা নয়।")
    st.write(f"**Required checks:** Momentum, Volatility, Selected Indicators, Candle Pattern, Risk/Reward এবং Structure অথবা Liquidity Sweep-এর অন্তত একটি PASS হতে হবে; মোট স্কোর কমপক্ষে 8/10।")
with right:
    st.subheader("Ten parameter checks")
    for i, (name, ok) in enumerate(chosen_checks, start=1):
        st.write(f"{'🟢' if ok else '🔴'} **{i}. {name}** — {'PASS' if ok else 'WAIT / FAIL'}")
    if side == "NEUTRAL":
        st.caption("BUY ও SELL স্কোর সমান; তাই কোনো দিক নির্বাচন করা হয়নি।")

with st.expander("🔍 কেন প্রতিটি শর্ত PASS/FAIL হচ্ছে? (Debug details)"):
    debug_rows = [
        ("Price / closed candle", f"{price:.8f}"),
        ("Previous 20-candle swing high", f"{float(last['swing_high']):.8f}"),
        ("Previous 20-candle swing low", f"{float(last['swing_low']):.8f}"),
        ("Previous 10-candle low", f"{prior_low10:.8f}"),
        ("Previous 10-candle high", f"{prior_high10:.8f}"),
        ("Support / Resistance", f"{support:.8f} / {resistance:.8f}"),
        ("Volume / 20-candle average", f"{float(last['volume']):.4f} / {float(last['vol_avg20']):.4f}"),
        ("Higher timeframe trend", "UP" if htf_up else ("DOWN" if htf_down else "NEUTRAL / unavailable")),
        ("Mandatory checks passed", "YES" if mandatory_ok else "NO"),
    ]
    st.dataframe(pd.DataFrame(debug_rows, columns=["Item", "Current value"]), use_container_width=True, hide_index=True)

if entry is not None:
    st.subheader("Signal levels (paper only)")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry reference", f"{entry:,.4f}")
    c2.metric("Stop Loss", f"{sl:,.4f}")
    c3.metric("Take Profit 1", f"{tp1:,.4f}")
    c4.metric("Take Profit 2", f"{tp2:,.4f}")
    st.caption("Entry reference হলো সর্বশেষ সম্পূর্ণ বন্ধ candle-এর close; বাস্তব execution price আলাদা হতে পারে।")

# ---------------- Optional AI review ----------------
st.divider()
st.subheader("🧠 Optional AI review")
st.write("AI review দ্বিতীয় মতামত মাত্র। API key কোডে লিখবেন না; Streamlit Secrets ব্যবহার করুন।")

def get_secret(name):
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except Exception:
        return os.getenv(name, "")

with st.expander("AI review চালু করার নির্দেশনা"):
    st.markdown('''Streamlit Cloud → App settings → Secrets-এ key যোগ করুন:

```toml
GEMINI_API_KEY = "তোমার_Gemini_API_key"
GROQ_API_KEY = "তোমার_Groq_API_key"
```
API key কাউকে পাঠাবে না এবং public GitHub code-এ রাখবে না।''')

if st.button("Run AI review now"):
    context = {
        "symbol": symbol, "timeframe": interval, "closed_candle_close": round(price, 8),
        "rsi14": round(float(last["rsi"]), 2), "atr14": round(atr, 8),
        "atr_percent": round(atr_pct, 4), "ema9": round(float(last["ema9"]), 8),
        "ema21": round(float(last["ema21"]), 8), "ema50": round(float(last["ema50"]), 8),
        "buy_checks_passed": buy_score, "sell_checks_passed": sell_score,
        "technical_status": ("CONFIRMED " + side) if confirmed else (("WARNING " + side) if warning else "NO TRADE"),
        "caution": "Do not invent live data; educational paper-trading prototype only."
    }
    prompt = ("তুমি crypto market analysis assistant। শুধু supplied numeric context ব্যবহার করে বাংলায় সংক্ষিপ্ত, সতর্ক review দাও। "
              "নতুন price বা indicator বানাবে না। score-কে win probability বলবে না। uncertainty, risk ও no-trade কারণ ব্যাখ্যা করো।\n" + str(context))
    got_any = False
    gkey = get_secret("GEMINI_API_KEY")
    if gkey:
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gkey}",
                json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=25)
            resp.raise_for_status()
            st.markdown("**Gemini review**")
            st.write(resp.json()["candidates"][0]["content"]["parts"][0]["text"])
            got_any = True
        except Exception as e:
            st.error(f"Gemini API error: {e}")
    grkey = get_secret("GROQ_API_KEY")
    if grkey:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {grkey}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.2},
                timeout=25)
            resp.raise_for_status()
            st.markdown("**Groq review**")
            st.write(resp.json()["choices"][0]["message"]["content"])
            got_any = True
        except Exception as e:
            st.error(f"Groq API error: {e}")
    if not got_any:
        st.info("AI key সেট করা নেই অথবা API কল সফল হয়নি। Technical dashboard চলতে থাকবে।")

# ---------------- Paper trading tracking ----------------
st.divider()
st.subheader("🧪 Paper Trading — TP/SL tracking")
st.caption("শুধু virtual trade। নতুন সম্পূর্ণ বন্ধ candle-এ TP/SL পরীক্ষা হয়। একই candle-এ SL ও TP একসঙ্গে ছুঁলে conservative ভাবে SL আগে ধরা হয়।")

# Track OPEN trades for the selected symbol. Each closed candle is processed once.
open_trades = [t for t in get_trades() if t["status"] == "OPEN" and t["symbol"] == symbol]
for trade in open_trades:
    trade_df, _ = get_klines(trade["symbol"], trade["interval"], 250)
    if trade_df is None or len(trade_df) < 3:
        continue
    closed_bars = trade_df.iloc[:-1].copy()
    signal_time = pd.to_datetime(trade["signal_time"], utc=True)
    processed_time = pd.to_datetime(trade["last_processed_close_time"] or trade["signal_time"], utc=True)
    # The signal candle is identified by its close_time; only process later bars.
    later_bars = closed_bars[closed_bars["close_time"] > max(signal_time, processed_time)]
    tp1_was_hit = bool(int(trade["tp1_hit"]))
    tp1_time_saved = trade["tp1_time"]
    for _, bar in later_bars.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        is_buy = trade["side"] == "BUY"
        sl_hit = lo <= float(trade["sl"]) if is_buy else hi >= float(trade["sl"])
        tp1_hit = hi >= float(trade["tp1"]) if is_buy else lo <= float(trade["tp1"])
        tp2_hit = hi >= float(trade["tp2"]) if is_buy else lo <= float(trade["tp2"])
        risk_usdt = float(trade["virtual_size_usdt"]) * abs(float(trade["entry"]) - float(trade["sl"])) / float(trade["entry"])
        bar_close_time = str(bar["close_time"])
        # If TP1 was already recorded, only the remaining half is at risk.
        if sl_hit:
            pnl = 0.0 if tp1_was_hit else -risk_usdt
            status = "CLOSED — TP1 THEN SL (approx. breakeven)" if tp1_was_hit else "CLOSED — SL HIT"
            update_trade(trade["id"], status=status, realized_pnl_usdt=pnl, exit_time=bar_close_time,
                         last_processed_close_time=bar_close_time)
            break
        if tp2_hit:
            # If TP2 is reached, TP1 is assumed reached first; 50% at 1R, 50% at 2R = +1.5R.
            update_trade(trade["id"], status="CLOSED — TP2 HIT", tp1_hit=1,
                         tp1_time=tp1_time_saved or bar_close_time,
                         realized_pnl_usdt=risk_usdt * 1.5, exit_time=bar_close_time,
                         last_processed_close_time=bar_close_time)
            break
        if tp1_hit and not tp1_was_hit:
            tp1_was_hit = True
            tp1_time_saved = bar_close_time
            update_trade(trade["id"], tp1_hit=1, tp1_time=bar_close_time,
                         last_processed_close_time=bar_close_time)
        else:
            update_trade(trade["id"], last_processed_close_time=bar_close_time)
    # end per-trade bars

# Create a paper trade only once per confirmed closed-candle signal.
if confirmed and side in ("BUY", "SELL"):
    signal_close_time = str(last["close_time"])
    signal_key = f"{symbol}-{interval}-{signal_close_time}-{side}"
    insert_trade({
        "signal_key": signal_key, "signal_time": signal_close_time,
        "symbol": symbol, "interval": interval, "side": side,
        "entry": float(entry), "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2),
        "virtual_size_usdt": float(paper_size), "created_at": datetime.now(timezone.utc).isoformat()
    })

trades_list = get_trades()
if trades_list:
    trades = pd.DataFrame(trades_list)
    closed = [t for t in trades_list if str(t["status"]).startswith("CLOSED")]
    wins = sum(1 for t in closed if t["realized_pnl_usdt"] is not None and float(t["realized_pnl_usdt"]) > 0)
    losses = sum(1 for t in closed if t["realized_pnl_usdt"] is not None and float(t["realized_pnl_usdt"]) < 0)
    total_pnl = sum(float(t["realized_pnl_usdt"] or 0) for t in closed)
    win_rate = (wins / len(closed) * 100) if closed else 0.0
    open_count = sum(1 for t in trades_list if t["status"] == "OPEN")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total virtual trades", str(len(trades_list)))
    k2.metric("Open trades", str(open_count))
    k3.metric("Closed-trade win rate", f"{win_rate:.1f}%", help="শুধু CLOSED trade গণনা করা হয়; open trade বাদ।")
    k4.metric("Realized virtual P&L", f"{total_pnl:+.4f} USDT", help="শুধু বন্ধ হওয়া trade; fee/slippage বাদ।")
    show_cols = ["id", "signal_time", "symbol", "interval", "side", "entry", "sl", "tp1", "tp2", "virtual_size_usdt", "tp1_hit", "status", "realized_pnl_usdt", "tp1_time", "exit_time"]
    st.dataframe(trades[show_cols], use_container_width=True, hide_index=True)
    st.caption("Simulation: TP1-এ ৫০% পজিশন 1R-এ বন্ধ, বাকি ৫০% TP2-তে 2R বা SL-এ বন্ধ। Fees, spread, slippage ও বাস্তব execution ধরা হয়নি।")
    if st.button("Clear all paper trade history"):
        clear_trades()
        st.rerun()
else:
    st.info("এখনো কোনো confirmed setup পাওয়া যায়নি। Trade History খালি থাকা স্বাভাবিক। বাজারে setup না থাকলে জোর করে trade তৈরি করা হবে না।")

st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
st.caption("Market data: Binance public spot klines. Data may be delayed or unavailable.")
# Streamlit rerun-based refresh; hosting may sleep or throttle.
time.sleep(0.2)
st.markdown(f'<meta http-equiv="refresh" content="{refresh_seconds}">', unsafe_allow_html=True)
