# Multi-AI Crypto Market Analysis Bot V1.0

A mobile-friendly Streamlit prototype for BTC/USDT-style crypto analysis on 5-minute candles.

## Included
- Public Binance spot candle data (no trading API key)
- 10 directional technical checks
- Advanced warning when a direction reaches 6/10 checks
- Confirmed signal only at 10/10 checks
- ATR-based entry reference, SL, TP1 (1R), TP2 (2R)
- Candlestick chart with EMA 9/21/50
- Optional Gemini and Groq review using Streamlit Secrets
- Basic session-only virtual paper trade history

## Important limitations
- Educational prototype, not financial advice, and no live orders.
- Progress is a count of conditions passed, not a win probability.
- Signal rules are intentionally strict and may produce very few signals.
- Current candle is excluded from confirmation to reduce intrabar repainting.
- Paper trade history is session-only and can be lost on restart/sleep.
- Free hosting/API quotas can change and are not guaranteed 24/7.
- This version does not yet evaluate whether TP/SL was hit from future candles, so it does not claim realized paper-trading P&L or backtest performance.

## Deploy from a phone
1. Create a GitHub repository.
2. Upload `app.py` and `requirements.txt`.
3. Open https://share.streamlit.io and sign in with GitHub.
4. Choose **Create app**, select your repository, and set main file path to `app.py`.
5. Deploy.
6. Open the deployed app URL on your phone.

## Optional AI keys
In Streamlit Cloud: App settings -> Secrets. Add one or both:

```toml
GEMINI_API_KEY = "your-key"
GROQ_API_KEY = "your-key"
```

Never commit API keys to GitHub. AI review is optional and does not override the technical signal engine.
