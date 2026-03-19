import os
import logging
import requests
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import io
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from datetime import datetime, timedelta
import mplfinance as mpf

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ISI_TOKEN_TELEGRAM_KAMU")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ISI_GEMINI_API_KEY_KAMU")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── HELPER: Ambil data saham IDX ────────────────────────────────────────────
def get_stock_data(kode: str, periode: str = "1mo"):
    ticker = kode.upper()
    if not ticker.endswith(".JK"):
        ticker += ".JK"
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=periode)
        info = stock.info
        return hist, info, ticker
    except Exception as e:
        logger.error(f"Error ambil data {ticker}: {e}")
        return None, None, ticker

# ─── HELPER: Buat chart candlestick ──────────────────────────────────────────
def buat_chart(kode: str, hist: pd.DataFrame) -> bytes:
    hist.index = pd.to_datetime(hist.index)
    hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()

    mc = mpf.make_marketcolors(
        up='#26a69a', down='#ef5350',
        edge='inherit', wick='inherit',
        volume={'up': '#26a69a', 'down': '#ef5350'}
    )
    s = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style='nightclouds',
        facecolor='#1a1a2e',
        figcolor='#1a1a2e',
        gridcolor='#2a2a4a',
        gridstyle='--'
    )

    buf = io.BytesIO()
    mpf.plot(
        hist,
        type='candle',
        style=s,
        title=f"\n  {kode.upper()} - Chart 1 Bulan",
        ylabel='Harga (IDR)',
        volume=True,
        mav=(20, 50),
        savefig=dict(fname=buf, dpi=120, bbox_inches='tight'),
        figsize=(12, 7)
    )
    buf.seek(0)
    return buf.read()

# ─── HELPER: Analisis dengan Gemini ──────────────────────────────────────────
def analisis_gemini(prompt: str, image_bytes: bytes = None) -> str:
    try:
        if image_bytes:
            image_part = {
                "mime_type": "image/png",
                "data": image_bytes
            }
            response = model.generate_content([prompt, image_part])
        else:
            response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ Error AI: {str(e)}"

# ─── COMMAND: /start ──────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pesan = """
🤖 *Bot Saham IDX — AI Powered*

Halo! Saya siap bantu analisis saham Indonesia kamu.

📋 *Perintah tersedia:*

📊 `/analisis BBRI` — Analisis teknikal + data saham
🔍 `/screening` — Kandidat saham hari ini  
🎯 `/entry BBRI` — Strategi entry, SL & TP
📈 `/chart BBRI` — Chart candlestick 1 bulan
ℹ️ `/info BBRI` — Info dasar emiten

📸 *Kirim screenshot chart TradingView* → AI langsung analisis!

_Contoh: /analisis BBRI atau /entry TLKM_
"""
    await update.message.reply_text(pesan, parse_mode="Markdown")

# ─── COMMAND: /analisis ───────────────────────────────────────────────────────
async def analisis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /analisis KODE\nContoh: /analisis BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Menganalisis {kode}...")

    hist, info, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan. Cek kode sahamnya ya.")
        return

    # Data terakhir
    harga_terakhir = hist['Close'].iloc[-1]
    harga_kemarin = hist['Close'].iloc[-2]
    perubahan = ((harga_terakhir - harga_kemarin) / harga_kemarin) * 100
    volume = hist['Volume'].iloc[-1]
    high_1m = hist['High'].max()
    low_1m = hist['Low'].min()
    ma20 = hist['Close'].rolling(20).mean().iloc[-1]
    ma50 = hist['Close'].rolling(50).mean().iloc[-1]
    rsi = hitung_rsi(hist['Close'])

    prompt = f"""Kamu adalah analis saham Indonesia yang berpengalaman. 
Analisis saham {kode} ({ticker}) dengan data berikut:

- Harga terakhir: Rp {harga_terakhir:,.0f}
- Perubahan: {perubahan:+.2f}%
- Volume: {volume:,.0f}
- High 1 bulan: Rp {high_1m:,.0f}
- Low 1 bulan: Rp {low_1m:,.0f}
- MA20: Rp {ma20:,.0f}
- MA50: Rp {ma50:,.0f}
- RSI (14): {rsi:.1f}

Berikan analisis teknikal singkat dalam Bahasa Indonesia:
1. Kondisi trend saat ini
2. Posisi harga vs MA20 & MA50
3. Interpretasi RSI
4. Kesimpulan singkat (bullish/bearish/sideways)

Format pakai emoji, singkat dan jelas. Maksimal 200 kata."""

    hasil_ai = analisis_gemini(prompt)

    # Buat chart
    try:
        chart_bytes = buat_chart(kode, hist)
        caption = f"""📊 *Analisis {kode}*

💰 Harga: Rp {harga_terakhir:,.0f} ({perubahan:+.2f}%)
📦 Volume: {volume:,.0f}
📈 MA20: Rp {ma20:,.0f}
📉 MA50: Rp {ma50:,.0f}
⚡ RSI: {rsi:.1f}

🤖 *AI Analysis:*
{hasil_ai}"""

        await update.message.reply_photo(
            photo=chart_bytes,
            caption=caption[:1024],
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"📊 *Analisis {kode}*\n\n🤖 {hasil_ai}", parse_mode="Markdown")

# ─── COMMAND: /entry ──────────────────────────────────────────────────────────
async def entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /entry KODE\nContoh: /entry BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Menghitung strategi entry {kode}...")

    hist, info, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan.")
        return

    harga = hist['Close'].iloc[-1]
    low_5d = hist['Low'].tail(5).min()
    high_5d = hist['High'].tail(5).max()
    ma20 = hist['Close'].rolling(20).mean().iloc[-1]
    rsi = hitung_rsi(hist['Close'])
    volume_avg = hist['Volume'].tail(20).mean()
    volume_last = hist['Volume'].iloc[-1]

    prompt = f"""Kamu adalah trader saham Indonesia berpengalaman.
Hitung strategi entry untuk saham {kode}:

Data:
- Harga saat ini: Rp {harga:,.0f}
- Low 5 hari: Rp {low_5d:,.0f}
- High 5 hari: Rp {high_5d:,.0f}
- MA20: Rp {ma20:,.0f}
- RSI: {rsi:.1f}
- Volume kemarin vs rata-rata: {(volume_last/volume_avg)*100:.0f}%

Berikan strategi entry trading jangka pendek dalam Bahasa Indonesia:
1. 🎯 Harga entry ideal (range)
2. 🛑 Stop Loss (harga + % dari entry)
3. ✅ Target Profit 1 (konservatif)
4. 🚀 Target Profit 2 (agresif)
5. ⚠️ Catatan risiko

Gunakan angka Rupiah yang spesifik. Format rapi dengan emoji."""

    hasil = analisis_gemini(prompt)
    await update.message.reply_text(f"🎯 *Strategi Entry {kode}*\n\n{hasil}", parse_mode="Markdown")

# ─── COMMAND: /screening ──────────────────────────────────────────────────────
async def screening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Screening saham IDX... (30 detik)")

    # Daftar saham IDX yang liquid
    kandidat_check = [
        "BBRI", "BBCA", "BMRI", "TLKM", "ASII",
        "GOTO", "BYAN", "ADRO", "INDF", "UNVR",
        "ICBP", "KLBF", "EXCL", "PGAS", "MEDC"
    ]

    hasil_screening = []

    for kode in kandidat_check:
        try:
            hist, _, _ = get_stock_data(kode, "3mo")
            if hist is None or len(hist) < 20:
                continue

            harga = hist['Close'].iloc[-1]
            harga_kemarin = hist['Close'].iloc[-2]
            perubahan = ((harga - harga_kemarin) / harga_kemarin) * 100
            ma20 = hist['Close'].rolling(20).mean().iloc[-1]
            volume = hist['Volume'].iloc[-1]
            vol_avg = hist['Volume'].rolling(20).mean().iloc[-1]
            rsi = hitung_rsi(hist['Close'])

            # Filter: uptrend + volume naik + RSI sehat
            if (harga > ma20 and
                volume > vol_avg * 1.2 and
                40 <= rsi <= 65):
                hasil_screening.append({
                    "kode": kode,
                    "harga": harga,
                    "perubahan": perubahan,
                    "rsi": rsi,
                    "vol_ratio": volume / vol_avg
                })
        except:
            continue

    if not hasil_screening:
        await update.message.reply_text("🔍 Tidak ada kandidat kuat hari ini. Market mungkin sideways atau overbought.")
        return

    pesan = "🔍 *Hasil Screening Saham IDX*\n"
    pesan += f"_{datetime.now().strftime('%d %b %Y')}_\n\n"
    pesan += "Kriteria: Uptrend + Volume naik + RSI sehat\n\n"

    for s in hasil_screening[:5]:
        emoji = "🟢" if s['perubahan'] >= 0 else "🔴"
        pesan += f"{emoji} *{s['kode']}*\n"
        pesan += f"   💰 Rp {s['harga']:,.0f} ({s['perubahan']:+.2f}%)\n"
        pesan += f"   ⚡ RSI: {s['rsi']:.0f} | Vol: {s['vol_ratio']:.1f}x avg\n\n"

    pesan += "_Gunakan /analisis KODE untuk analisis lengkap_"
    await update.message.reply_text(pesan, parse_mode="Markdown")

# ─── COMMAND: /chart ──────────────────────────────────────────────────────────
async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /chart KODE\nContoh: /chart BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Membuat chart {kode}...")

    hist, _, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan.")
        return

    try:
        chart_bytes = buat_chart(kode, hist)
        await update.message.reply_photo(
            photo=chart_bytes,
            caption=f"📈 *Chart {kode} — 1 Bulan*\n_MA20 (biru) | MA50 (oranye)_",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal buat chart: {str(e)}")

# ─── COMMAND: /info ───────────────────────────────────────────────────────────
async def info_saham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /info KODE\nContoh: /info BBRI")
        return

    kode = context.args[0].upper()
    hist, info, ticker = get_stock_data(kode)

    if hist is None:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan.")
        return

    nama = info.get('longName', kode)
    sektor = info.get('sector', 'N/A')
    market_cap = info.get('marketCap', 0)
    pe = info.get('trailingPE', 0)
    pb = info.get('priceToBook', 0)
    div_yield = info.get('dividendYield', 0)

    pesan = f"""ℹ️ *Info Emiten: {kode}*

🏢 Nama: {nama}
🏭 Sektor: {sektor}
💼 Market Cap: Rp {market_cap/1e12:.1f} T
📊 P/E Ratio: {pe:.1f}x
📚 P/B Ratio: {pb:.1f}x
💰 Div. Yield: {(div_yield or 0)*100:.2f}%

_Data dari Yahoo Finance_"""

    await update.message.reply_text(pesan, parse_mode="Markdown")

# ─── HANDLER: Foto/Screenshot dari TradingView ────────────────────────────────
async def handle_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Screenshot diterima! Menganalisis chart... ⏳")

    foto = update.message.photo[-1]
    file = await context.bot.get_file(foto.file_id)
    
    foto_bytes = await file.download_as_bytearray()

    prompt = """Kamu adalah analis teknikal saham berpengalaman.
Analisis chart saham pada gambar ini dalam Bahasa Indonesia:

1. 📈 Identifikasi trend (uptrend/downtrend/sideways)
2. 🔑 Level support dan resistance yang terlihat
3. 📊 Pola candlestick yang muncul (jika ada)
4. ⚡ Kondisi indikator (jika terlihat: RSI, MA, MACD, dll)
5. 🎯 Rekomendasi: Buy / Hold / Wait / Sell
6. ⚠️ Risiko yang perlu diperhatikan

Format dengan emoji, jelas dan actionable."""

    hasil = analisis_gemini(prompt, bytes(foto_bytes))
    await update.message.reply_text(
        f"🤖 *Analisis Chart AI*\n\n{hasil}",
        parse_mode="Markdown"
    )

# ─── HELPER: Hitung RSI ───────────────────────────────────────────────────────
def hitung_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("analisis", analisis))
    app.add_handler(CommandHandler("entry", entry))
    app.add_handler(CommandHandler("screening", screening))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("info", info_saham))
    app.add_handler(MessageHandler(filters.PHOTO, handle_foto))

    logger.info("🤖 Bot Saham IDX started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
