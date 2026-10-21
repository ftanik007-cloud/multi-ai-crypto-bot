# Multi-AI Crypto Bot V1.5 PRO — বাংলা নির্দেশিকা

## V1.5-এ যোগ হয়েছে
- সর্বোচ্চ OPEN paper trade সীমা (default 5)
- দৈনিক realized loss limit (default 20 USDT; 0 দিলে বন্ধ)
- নতুন unique paper trade তৈরি হলে optional Telegram alert
- UTC অনুযায়ী দৈনিক ও সাপ্তাহিক closed-trade report
- V1.4-এর TP/SL tracking, dashboard, CSV export, backtest, PostgreSQL/SQLite storage রাখা হয়েছে

## Android/GitHub দিয়ে আপডেট
1. আগে V1.4-এর CSV Trade History backup রাখো।
2. `Multi_AI_Crypto_Bot_V1_5_PRO_app.py` ডাউনলোড করে GitHub repository-তে আপলোড করো এবং ফাইলের নাম `app.py` রাখো/পুরোনো `app.py`-এর বদলে বসাও।
3. `requirements.txt` V1.4-এর মতোই ব্যবহার করা যায়: streamlit, requests, numpy, pandas, plotly, SQLAlchemy, psycopg[binary]
4. Commit changes করে Streamlit deployment শেষ হওয়া পর্যন্ত অপেক্ষা করো।
5. Dashboard, নতুন paper trade, report ও backtest আবার পরীক্ষা করো।

## Telegram alerts (ঐচ্ছিক)
Telegram-এ @BotFather দিয়ে bot তৈরি করো, bot-এ /start পাঠাও, chat ID বের করো। Streamlit Cloud → App settings → Secrets-এ যোগ করো:

```toml
TELEGRAM_BOT_TOKEN = "তোমার_bot_token"
TELEGRAM_CHAT_ID = "তোমার_chat_id"
```

Token কখনো GitHub-এ বা ChatGPT-তে পাঠাবে না। Alert শুধু তখন পাঠানো হয় যখন অ্যাপের rerun-এ নতুন unique paper trade তৈরি হয়। এটি background scanner নয়; অ্যাপ বন্ধ থাকলে 24/7 scan করবে না।

## Risk guard কী করে
- Maximum open paper trades পূর্ণ হলে নতুন paper trade তৈরি হতে বাধা দেয়।
- দৈনিক realized P&L configured loss limit-এ পৌঁছালে নতুন paper trade ব্লক করে। Open trade-এর unrealized loss এই guard-এ গণনা হয় না; রিপোর্ট UTC সময় ধরে।
- সবই paper trading; বাস্তব exchange order পাঠানো হয় না। লাভ নিশ্চিত নয়।

## গুরুত্বপূর্ণ সীমাবদ্ধতা
- এই সংস্করণে UI-তে এক সময়ে একটি নির্বাচিত pair বিশ্লেষণ করা হয়; স্বয়ংক্রিয় বহু-coin background scanning নেই।
- Telegram alert পেতে অ্যাপ সচল/রিরান হওয়া দরকার।
- Backtest আনুমানিক; fees, spread ও slippage অন্তর্ভুক্ত নয়।
- PostgreSQL সংযোগ ও persistence আলাদাভাবে যাচাই করতে হবে।
