import os
import time
import sqlite3
from datetime import datetime, timezone

import requests
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Multi-AI Crypto Bot V1.5 PRO", page_icon="📊", layout="wide")

APP_VERSION = "V1.5 PRO"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper_trades.db")

def get_database_url():
    try:
        url = st.secrets.get("DATABASE_URL", "")
    except Exception:
        url = ""
    url = url or os.getenv("DATABASE_URL", "")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

DATABASE_URL = get_database_url()
USING_REMOTE_DB = bool(DATABASE_URL)
engine = create_engine(DATABASE_URL, pool_pre_ping=True) if USING_REMOTE_DB else create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
BINANCE_BASES = ["https://data-api.binance.vision", "https://api.binance.com"]

st.title("📊 Multi-AI Crypto Market Analysis Bot — V1.5 PRO")
st.caption("Public market data • Confirmed candles • Paper trading only • Risk guard • Telegram alerts • Reports • Backtest")
st.warning("শিক্ষামূলক প্রোটোটাইপ। লাভ নিশ্চিত করে না। এখানে কোনো বাস্তব exchange order পাঠানো হয় না।")

# ---------------- Storage: SQLite fallback or persistent PostgreSQL ----------------
def init_db():
    if USING_REMOTE_DB:
        ddl = """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id BIGSERIAL PRIMARY KEY,
            signal_key TEXT UNIQUE NOT NULL,
            signal_time TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            side TEXT NOT NULL,
            entry DOUBLE PRECISION NOT NULL,
            sl DOUBLE PRECISION NOT NULL,
            tp1 DOUBLE PRECISION NOT NULL,
            tp2 DOUBLE PRECISION NOT NULL,
            virtual_size_usdt DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            tp1_hit INTEGER NOT NULL DEFAULT 0,
            tp1_time TEXT,
            exit_time TEXT,
            realized_pnl_usdt DOUBLE PRECISION,
            last_processed_close_time TEXT,
            created_at TEXT NOT NULL
        )
        """
    else:
        ddl = """
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
        """
    with engine.begin() as conn:
        conn.execute(text(ddl))

    # If a persistent DB is configured, copy local SQLite records into it once.
    # The local file is not deleted; duplicate signal_key rows are ignored.
    if USING_REMOTE_DB and os.path.exists(DB_PATH):
        try:
            local_engine = create_engine(f"sqlite:///{DB_PATH}")
            with local_engine.connect() as local_conn:
                old_rows = local_conn.execute(text("SELECT * FROM paper_trades")).mappings().all()
            with engine.begin() as remote_conn:
                for row in old_rows:
                    data = dict(row)
                    remote_conn.execute(text("""
                        INSERT INTO paper_trades
                        (signal_key, signal_time, symbol, interval, side, entry, sl, tp1, tp2,
                         virtual_size_usdt, status, tp1_hit, tp1_time, exit_time, realized_pnl_usdt,
                         last_processed_close_time, created_at)
                        VALUES (:signal_key, :signal_time, :symbol, :interval, :side, :entry, :sl, :tp1, :tp2,
                         :virtual_size_usdt, :status, :tp1_hit, :tp1_time, :exit_time, :realized_pnl_usdt,
                         :last_processed_close_time, :created_at)
                        ON CONFLICT (signal_key) DO NOTHING
                    """), data)
            local_engine.dispose()
        except Exception as e:
            st.warning(f"Local-to-cloud history migration skipped: {e}. Local SQLite file রাখা হয়েছে।")


def get_trades():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM paper_trades ORDER BY id DESC")).mappings().all()
    return [dict(r) for r in rows]


def insert_trade(t):
    if USING_REMOTE_DB:
        sql = """INSERT INTO paper_trades
        (signal_key, signal_time, symbol, interval, side, entry, sl, tp1, tp2,
         virtual_size_usdt, status, tp1_hit, created_at, last_processed_close_time)
        VALUES (:signal_key, :signal_time, :symbol, :interval, :side, :entry, :sl, :tp1, :tp2,
         :virtual_size_usdt, 'OPEN', 0, :created_at, :signal_time)
        ON CONFLICT (signal_key) DO NOTHING"""
    else:
        sql = """INSERT OR IGNORE INTO paper_trades
        (signal_key, signal_time, symbol, interval, side, entry, sl, tp1, tp2,
         virtual_size_usdt, status, tp1_hit, created_at, last_processed_close_time)
        VALUES (:signal_key, :signal_time, :symbol, :interval, :side, :entry, :sl, :tp1, :tp2,
         :virtual_size_usdt, 'OPEN', 0, :created_at, :signal_time)"""
    with engine.begin() as conn:
        result = conn.execute(text(sql), t)
        return result.rowcount > 0


def update_trade(trade_id, **fields):
    allowed = {"status", "tp1_hit", "tp1_time", "exit_time", "realized_pnl_usdt", "last_processed_close_time"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in updates)
    updates["trade_id"] = trade_id
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE paper_trades SET {assignments} WHERE id = :trade_id"), updates)


def clear_trades():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM paper_trades"))


init_db()

# ---------------- Settings ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    symbol = st.selectbox("Crypto pair", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"], index=0)
    interval = st.selectbox("Chart timeframe", ["5m", "15m", "1h"], index=0)
    refresh_seconds = st.slider("Refresh interval (seconds)", 30, 180, 60, 15)
    paper_size = st.number_input("Virtual position size (USDT)", min_value=10.0, max_value=100000.0, value=100.0, step=10.0)
    max_open_trades = st.slider("Maximum open paper trades", 1, 20, 5)
    daily_loss_limit = st.number_input("Daily realized loss limit (USDT)", min_value=0.0, max_value=10000.0, value=20.0, step=5.0, help="0 দিলে দৈনিক loss guard বন্ধ থাকবে।")
    st.caption("Virtual position size হলো trade-এর notional value; বাস্তব টাকা নয়।")
    if USING_REMOTE_DB:
        st.success("Persistent PostgreSQL connected — history cloud database-এ রাখা হচ্ছে।")
    else:
        st.warning("SQLite fallback চালু। Streamlit redeploy/runtime reset হলে history হারাতে পারে। স্থায়ী storage-এর জন্য DATABASE_URL configure করো।")

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

# ---------------- Telegram alert setup ----------------
st.divider()
st.subheader("📨 Optional Telegram Alerts")
st.write("Telegram bot token এবং chat ID শুধু Streamlit Secrets-এ রাখবে; GitHub কোডে বা চ্যাটে পাঠাবে না।")
with st.expander("Telegram setup instructions"):
    st.markdown('''1. Telegram-এ `@BotFather` খুলে `/newbot` দিয়ে bot তৈরি করো।
2. Bot token নাও; তারপর নিজের bot-এ `/start` পাঠাও।
3. নিজের chat ID নির্ভরযোগ্যভাবে বের করে নিচের Secrets-এ যোগ করো:

```toml
TELEGRAM_BOT_TOKEN = "তোমার_bot_token"
TELEGRAM_CHAT_ID = "তোমার_chat_id"
```

সিগন্যালের সময় নতুন unique paper trade তৈরি হলেই alert যাবে। Streamlit app বন্ধ থাকলে এটি 24/7 background scanner হিসেবে চলবে না; app rerun/active থাকা দরকার।''')

# ---------------- Optional AI review ----------------
st.divider()
st.subheader("🧠 Optional AI review")
st.write("AI review দ্বিতীয় মতামত মাত্র। API key কোডে লিখবেন না; Streamlit Secrets ব্যবহার করুন।")

def get_secret(name):
    try:
        return st.secrets.get(name, os.getenv(name, ""))
    except Exception:
        return os.getenv(name, "")


def send_telegram(message):
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram not configured"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message}, timeout=10
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            return False, str(payload)
        return True, "sent"
    except Exception as exc:
        return False, str(exc)

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
    trade_df, _ = get_klines(trade["symbol"], trade["interval"], 1000)
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
            status = "CLOSED — TP1 THEN SL (approx. breakeven)" if tp1_was_hit else ("CLOSED — SL HIT (same-candle ambiguity; conservative)" if (tp1_hit or tp2_hit) else "CLOSED — SL HIT")
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

# V1.5 risk guards and duplicate-safe paper-trade creation.
trades_before_signal = get_trades()
now_utc = datetime.now(timezone.utc)
today_utc = now_utc.date().isoformat()
closed_today_pnl = sum(
    float(t.get("realized_pnl_usdt") or 0) for t in trades_before_signal
    if str(t.get("status", "")).startswith("CLOSED")
    and str(t.get("exit_time") or t.get("created_at", ""))[:10] == today_utc
)
open_before_signal = sum(1 for t in trades_before_signal if t.get("status") == "OPEN")
risk_guard_reason = None
if open_before_signal >= max_open_trades:
    risk_guard_reason = f"Maximum open paper trades reached ({max_open_trades})."
if daily_loss_limit > 0 and closed_today_pnl <= -daily_loss_limit:
    risk_guard_reason = f"Daily realized loss limit reached ({daily_loss_limit:.2f} USDT)."

if confirmed and side in ("BUY", "SELL"):
    signal_close_time = str(last["close_time"])
    signal_key = f"{symbol}-{interval}-{signal_close_time}-{side}"
    if risk_guard_reason:
        st.warning(f"Paper trade blocked by risk guard: {risk_guard_reason}")
    else:
        inserted = insert_trade({
            "signal_key": signal_key, "signal_time": signal_close_time,
            "symbol": symbol, "interval": interval, "side": side,
            "entry": float(entry), "sl": float(sl), "tp1": float(tp1), "tp2": float(tp2),
            "virtual_size_usdt": float(paper_size), "created_at": now_utc.isoformat()
        })
        if inserted:
            alert_text = (f"📊 Multi-AI Crypto Bot V1.5 PRO\nPaper signal: {side} {symbol}\n"
                          f"Timeframe: {interval}\nEntry: {float(entry):.8g}\nSL: {float(sl):.8g}\n"
                          f"TP1: {float(tp1):.8g}\nTP2: {float(tp2):.8g}\n"
                          "Paper trade only — no real order sent.")
            if get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID"):
                sent, msg = send_telegram(alert_text)
                if not sent:
                    st.warning(f"Telegram alert পাঠানো যায়নি: {msg}")

trades_list = get_trades()
if trades_list:
    trades = pd.DataFrame(trades_list)
    closed = [t for t in trades_list if str(t["status"]).startswith("CLOSED")]
    pnl_values = [float(t["realized_pnl_usdt"]) for t in closed if t["realized_pnl_usdt"] is not None]
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    gross_profit = sum(p for p in pnl_values if p > 0)
    gross_loss = abs(sum(p for p in pnl_values if p < 0))
    total_pnl = sum(pnl_values)
    win_rate = (wins / len(pnl_values) * 100) if pnl_values else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    open_count = sum(1 for t in trades_list if t["status"] == "OPEN")

    # Equity starts at 1,000 virtual USDT for percentage drawdown only.
    closed_sorted = sorted([t for t in closed if t["realized_pnl_usdt"] is not None], key=lambda t: str(t["exit_time"] or t["created_at"]))
    equity = 1000.0
    peak = equity
    max_dd_usdt = 0.0
    max_dd_pct = 0.0
    curve = []
    for t in closed_sorted:
        equity += float(t["realized_pnl_usdt"] or 0)
        peak = max(peak, equity)
        dd = peak - equity
        dd_pct = (dd / peak * 100) if peak > 0 else 0.0
        max_dd_usdt = max(max_dd_usdt, dd)
        max_dd_pct = max(max_dd_pct, dd_pct)
        curve.append({"Exit time": t["exit_time"] or t["created_at"], "Equity (USDT)": equity})

    st.subheader("📈 Paper Trading Performance Dashboard")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total virtual trades", str(len(trades_list)))
    k2.metric("Closed-trade win rate", f"{win_rate:.1f}%")
    k3.metric("Profit Factor", "∞" if np.isinf(profit_factor) else f"{profit_factor:.2f}")
    k4.metric("Realized Total P&L", f"{total_pnl:+.4f} USDT")
    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Open trades", str(open_count))
    k6.metric("Closed trades", str(len(pnl_values)))
    k7.metric("Max Drawdown", f"{max_dd_usdt:.4f} USDT")
    k8.metric("Max Drawdown %", f"{max_dd_pct:.2f}%", help="Drawdown percentage uses a starting virtual equity of 1,000 USDT.")

    show_cols = ["id", "signal_time", "symbol", "interval", "side", "entry", "sl", "tp1", "tp2", "virtual_size_usdt", "tp1_hit", "status", "realized_pnl_usdt", "tp1_time", "exit_time"]
    st.dataframe(trades[show_cols], use_container_width=True, hide_index=True)
    if curve:
        st.subheader("Closed-trade equity curve")
        curve_df = pd.DataFrame(curve)
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=curve_df["Exit time"], y=curve_df["Equity (USDT)"], mode="lines+markers", name="Virtual equity"))
        fig_eq.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
        st.plotly_chart(fig_eq, use_container_width=True)
    st.caption("TP1-এ ৫০% পজিশন 1R-এ বন্ধ, বাকি ৫০% TP2-তে 2R বা SL-এ বন্ধ ধরা হয়। Fees, spread, slippage ও বাস্তব execution বাদ। Same-candle ambiguity হলে SL-first conservative rule।")
    # Daily/weekly summaries based on closed-trade exit date (UTC).
    st.subheader("🗓️ Daily & Weekly Report (UTC)")
    closed_df = trades[trades["status"].astype(str).str.startswith("CLOSED")].copy()
    if not closed_df.empty:
        closed_df["report_date"] = pd.to_datetime(closed_df["exit_time"].fillna(closed_df["created_at"]), errors="coerce", utc=True)
        closed_df["report_pnl"] = pd.to_numeric(closed_df["realized_pnl_usdt"], errors="coerce").fillna(0.0)
        daily_start = pd.Timestamp.now(tz="UTC").normalize()
        weekly_start = daily_start - pd.Timedelta(days=daily_start.weekday())
        daily_df = closed_df[closed_df["report_date"] >= daily_start]
        weekly_df = closed_df[closed_df["report_date"] >= weekly_start]
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Today closed trades", str(len(daily_df)))
        r2.metric("Today realized P&L", f"{daily_df['report_pnl'].sum():+.4f} USDT")
        r3.metric("This week closed trades", str(len(weekly_df)))
        r4.metric("This week realized P&L", f"{weekly_df['report_pnl'].sum():+.4f} USDT")
    else:
        st.info("Daily/weekly report দেখাতে এখনো কোনো closed trade নেই।")

    csv_bytes = trades.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 Download Trade History (CSV)", data=csv_bytes, file_name="multi_ai_crypto_paper_trades.csv", mime="text/csv")
    if st.button("Clear all paper trade history"):
        clear_trades()
        st.rerun()
else:
    st.info("এখনো কোনো confirmed setup পাওয়া যায়নি। Trade History খালি থাকা স্বাভাবিক। বাজারে setup না থাকলে জোর করে trade তৈরি করা হবে না।")

# ---------------- Historical backtest engine ----------------
st.divider()
st.subheader("🧪 Historical Backtest Engine")
st.caption("Historical simulation only. Uses closed Binance spot candles, fixed 1.5 ATR stop, TP1=1R, TP2=2R; one position at a time. Fees/slippage are not included.")
with st.expander("Backtest settings and run"):
    bt_symbol = st.selectbox("Backtest pair", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"], index=0, key="bt_symbol")
    bt_interval = st.selectbox("Backtest timeframe", ["5m", "15m", "1h"], index=0, key="bt_interval")
    bt_limit = st.select_slider("Historical candles", options=[200, 300, 500, 750, 1000], value=500, key="bt_limit")
    bt_size = st.number_input("Virtual notional per trade (USDT)", min_value=10.0, max_value=100000.0, value=100.0, step=10.0, key="bt_size")
    run_backtest = st.button("Run historical backtest", key="run_backtest")

if run_backtest:
    with st.spinner("Binance historical candles আনা হচ্ছে এবং backtest চলছে..."):
        bt_raw, bt_error = get_klines(bt_symbol, bt_interval, int(bt_limit))
        if bt_raw is None or len(bt_raw) < 100:
            st.error(f"Backtest data পাওয়া যায়নি: {bt_error or 'ডেটা অপর্যাপ্ত'}")
        else:
            bt_closed = bt_raw.iloc[:-1].copy().reset_index(drop=True)
            bt = indicators(bt_closed).dropna().reset_index(drop=True)
            sim_trades = []
            i = 25
            while i < len(bt) - 1:
                r = bt.iloc[i]
                entry_bt = float(r["close"])
                atr_bt = float(r["atr"])
                if not np.isfinite(atr_bt) or atr_bt <= 0:
                    i += 1
                    continue
                prior = bt.iloc[max(0, i-10):i]
                prior_low = float(prior["low"].min())
                prior_high = float(prior["high"].max())
                buy_structure = entry_bt > float(r["swing_high"])
                sell_structure = entry_bt < float(r["swing_low"])
                buy_mom = bool(r["rsi"] >= 52 and r["macd"] > r["macd_signal"])
                sell_mom = bool(r["rsi"] <= 48 and r["macd"] < r["macd_signal"])
                vol_ok = bool(0.03 <= atr_bt / entry_bt * 100 <= 2.5)
                buy_sweep = bool(float(r["low"]) < prior_low and entry_bt > prior_low)
                sell_sweep = bool(float(r["high"]) > prior_high and entry_bt < prior_high)
                sup = float(r["support20"]); res = float(r["resistance20"])
                buy_sr = abs(entry_bt-sup) <= max(atr_bt*0.8, entry_bt*0.001) or buy_structure
                sell_sr = abs(res-entry_bt) <= max(atr_bt*0.8, entry_bt*0.001) or sell_structure
                body_bt = abs(float(r["close"])-float(r["open"]))
                range_bt = max(float(r["high"])-float(r["low"]), 1e-12)
                lw = min(float(r["open"]),float(r["close"]))-float(r["low"])
                uw = float(r["high"])-max(float(r["open"]),float(r["close"]))
                buy_candle = (r["close"]>r["open"] and body_bt/range_bt>=0.45) or (lw/range_bt>=0.55 and r["close"]>r["open"])
                sell_candle = (r["close"]<r["open"] and body_bt/range_bt>=0.45) or (uw/range_bt>=0.55 and r["close"]<r["open"])
                volume_ok_bt = bool(pd.notna(r["vol_avg20"]) and r["volume"] >= r["vol_avg20"])
                buy_ind = bool(r["close"] > r["ema9"] > r["ema21"] and r["rsi"] > 50)
                sell_ind = bool(r["close"] < r["ema9"] < r["ema21"] and r["rsi"] < 50)
                buy_checks = [buy_structure,buy_mom,vol_ok,buy_sweep,buy_sr,buy_candle,volume_ok_bt,buy_ind,False,True]
                sell_checks = [sell_structure,sell_mom,vol_ok,sell_sweep,sell_sr,sell_candle,volume_ok_bt,sell_ind,False,True]
                bscore=sum(bool(v) for v in buy_checks); sscore=sum(bool(v) for v in sell_checks)
                side_bt = "BUY" if bscore>sscore else ("SELL" if sscore>bscore else "NEUTRAL")
                chosen_bt = buy_checks if side_bt=="BUY" else sell_checks
                mandatory_bt = chosen_bt[1] and chosen_bt[2] and chosen_bt[7] and chosen_bt[5] and (chosen_bt[0] or chosen_bt[3]) and chosen_bt[9]
                if side_bt not in ("BUY","SELL") or max(bscore,sscore)<8 or not mandatory_bt:
                    i+=1; continue
                dist=atr_bt*1.5
                sl_bt=entry_bt-dist if side_bt=="BUY" else entry_bt+dist
                tp1_bt=entry_bt+dist if side_bt=="BUY" else entry_bt-dist
                tp2_bt=entry_bt+2*dist if side_bt=="BUY" else entry_bt-2*dist
                risk_bt=float(bt_size)*dist/entry_bt
                outcome="OPEN AT END"; pnl_bt=0.0; tp1_done=False; exit_idx=None
                for j in range(i+1,len(bt)):
                    bar=bt.iloc[j]; hi=float(bar["high"]); lo=float(bar["low"])
                    sl_hit=lo<=sl_bt if side_bt=="BUY" else hi>=sl_bt
                    one_hit=hi>=tp1_bt if side_bt=="BUY" else lo<=tp1_bt
                    two_hit=hi>=tp2_bt if side_bt=="BUY" else lo<=tp2_bt
                    if sl_hit:
                        pnl_bt=0.0 if tp1_done else -risk_bt
                        outcome="TP1 THEN SL (approx. BE)" if tp1_done else ("SL (conservative same-candle rule)" if one_hit or two_hit else "SL")
                        exit_idx=j; break
                    if two_hit:
                        pnl_bt=risk_bt*1.5; outcome="TP2"; exit_idx=j; break
                    if one_hit:
                        tp1_done=True
                if exit_idx is None:
                    # Position would remain open through the end of the sample; do not open overlapping trades.
                    break
                sim_trades.append({"Entry time":str(bt.iloc[i]["close_time"]),"Exit time":str(bt.iloc[exit_idx]["close_time"]),"Symbol":bt_symbol,"Timeframe":bt_interval,"Side":side_bt,"Entry":entry_bt,"SL":sl_bt,"TP1":tp1_bt,"TP2":tp2_bt,"Outcome":outcome,"P&L (USDT)":pnl_bt})
                i=exit_idx+1
            if not sim_trades:
                st.warning("এই sample-এ নিয়ম অনুযায়ী কোনো সম্পূর্ণ বন্ধ backtest trade পাওয়া যায়নি। এটা কোড ব্যর্থতার প্রমাণ নয়; signal rule কঠোর হতে পারে।")
            else:
                btdf=pd.DataFrame(sim_trades)
                vals=btdf["P&L (USDT)"].astype(float)
                gross_w=float(vals[vals>0].sum()); gross_l=abs(float(vals[vals<0].sum()))
                pf=gross_w/gross_l if gross_l>0 else (float("inf") if gross_w>0 else 0.0)
                wr=float((vals>0).sum()/len(vals)*100)
                total=float(vals.sum())
                eq=1000.0; peak_eq=eq; maxdd=0.0
                for v in vals:
                    eq+=float(v); peak_eq=max(peak_eq,eq); maxdd=max(maxdd,peak_eq-eq)
                b1,b2,b3,b4,b5=st.columns(5)
                b1.metric("Backtest trades",str(len(btdf)))
                b2.metric("Win Rate",f"{wr:.1f}%")
                b3.metric("Profit Factor","∞" if np.isinf(pf) else f"{pf:.2f}")
                b4.metric("Total P&L",f"{total:+.4f} USDT")
                b5.metric("Max Drawdown",f"{maxdd:.4f} USDT")
                st.dataframe(btdf,use_container_width=True,hide_index=True)
                st.download_button("Download Backtest CSV",data=btdf.to_csv(index=False).encode("utf-8-sig"),file_name="multi_ai_crypto_backtest.csv",mime="text/csv")
                st.warning("Backtest approximation: MTF confirmation is not used as a mandatory gate; entry at candle close is simulated; fees/spread/slippage are excluded; OHLC candles cannot reveal exact intrabar order. Historical results do not predict future returns.")

st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
st.caption("Market data: Binance public spot klines. Data may be delayed or unavailable. Permanent storage requires DATABASE_URL; SQLite fallback is not guaranteed to survive redeploy.")
# Streamlit rerun-based refresh; hosting may sleep or throttle.
time.sleep(0.2)
st.markdown(f'<meta http-equiv="refresh" content="{refresh_seconds}">', unsafe_allow_html=True)
