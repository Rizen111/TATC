import os
import logging
import requests
import matplotlib.pyplot as plt
import pandas as pd
import io
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ISI_TOKEN_TELEGRAM_KAMU")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ISI_GEMINI_API_KEY_KAMU")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "ISI_ALPHA_VANTAGE_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── REQUEST COUNTER ──────────────────────────────────────────────────────────
MAX_REQUEST_HARIAN = 25
_counter = {"tanggal": "", "terpakai": 0}

def pakai_request(jumlah: int = 1) -> dict:
    hari_ini = datetime.now().strftime("%Y-%m-%d")
    if _counter["tanggal"] != hari_ini:
        _counter["tanggal"] = hari_ini
        _counter["terpakai"] = 0
    _counter["terpakai"] += jumlah
    sisa = MAX_REQUEST_HARIAN - _counter["terpakai"]
    return {"terpakai": _counter["terpakai"], "sisa": max(0, sisa)}

def cek_request(jumlah: int = 1) -> bool:
    hari_ini = datetime.now().strftime("%Y-%m-%d")
    if _counter["tanggal"] != hari_ini:
        return True
    return (_counter["terpakai"] + jumlah) <= MAX_REQUEST_HARIAN

def status_request() -> str:
    hari_ini = datetime.now().strftime("%Y-%m-%d")
    if _counter["tanggal"] != hari_ini:
        terpakai, sisa = 0, MAX_REQUEST_HARIAN
    else:
        terpakai = _counter["terpakai"]
        sisa = max(0, MAX_REQUEST_HARIAN - terpakai)
    if sisa >= 15:
        emoji = "🟢"
    elif sisa >= 8:
        emoji = "🟡"
    elif sisa > 0:
        emoji = "🔴"
    else:
        emoji = "⛔"
    return f"{emoji} API: {sisa}/{MAX_REQUEST_HARIAN} request sisa hari ini"


# ─── HELPER: Ambil data dari Alpha Vantage ────────────────────────────────────
def get_stock_data(kode: str, periode: str = "1mo"):
    ticker = kode.upper().strip()
    # Alpha Vantage pakai format BBRI.JKT untuk IDX
    ticker = ticker.replace(".JK", "").replace(".JKT", "")
    ticker_av = ticker + ".JKT"

    try:
        url = "https://www.alphavantage.co/query"
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker_av,
            "outputsize": "compact",
            "apikey": ALPHA_VANTAGE_KEY
        }
        response = requests.get(url, params=params, timeout=15)
        data = response.json()

        if "Time Series (Daily)" not in data:
            logger.error(f"Alpha Vantage error untuk {ticker_av}: {data}")
            return None, {}, ticker_av

        ts = data["Time Series (Daily)"]
        rows = []
        for date_str, vals in ts.items():
            rows.append({
                "Date": pd.to_datetime(date_str),
                "Open": float(vals["1. open"]),
                "High": float(vals["2. high"]),
                "Low": float(vals["3. low"]),
                "Close": float(vals["4. close"]),
                "Volume": float(vals["5. volume"]),
            })

        hist = pd.DataFrame(rows)
        hist.set_index("Date", inplace=True)
        hist.sort_index(inplace=True)

        if periode == "1mo":
            hist = hist.last("30D")
        elif periode == "3mo":
            hist = hist.last("90D")
        elif periode == "6mo":
            hist = hist.last("180D")

        logger.info(f"Data {ticker_av} OK ({len(hist)} baris)")
        return hist, {}, ticker_av

    except Exception as e:
        logger.error(f"Error ambil data {ticker_av}: {e}")
        return None, {}, ticker_av

# ─── HELPER: Hitung RSI ───────────────────────────────────────────────────────
def hitung_rsi(prices: pd.Series, period: int = 14) -> float:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else 50.0

# ─── HELPER: Buat chart candlestick ──────────────────────────────────────────
def buat_chart(kode: str, hist: pd.DataFrame) -> bytes:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                    gridspec_kw={'height_ratios': [3, 1]},
                                    facecolor='#1a1a2e')
    ax1.set_facecolor('#1a1a2e')
    ax2.set_facecolor('#1a1a2e')

    dates = list(range(len(hist)))
    opens = hist['Open'].values
    closes = hist['Close'].values
    highs = hist['High'].values
    lows = hist['Low'].values
    volumes = hist['Volume'].values

    for i in dates:
        color = '#26a69a' if closes[i] >= opens[i] else '#ef5350'
        ax1.bar(i, abs(closes[i] - opens[i]),
                bottom=min(opens[i], closes[i]),
                color=color, width=0.6, alpha=0.9)
        ax1.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8)

    if len(hist) >= 20:
        ma20 = hist['Close'].rolling(20).mean().values
        ax1.plot(dates, ma20, color='#2196F3', linewidth=1.5, label='MA20')
    if len(hist) >= 50:
        ma50 = hist['Close'].rolling(50).mean().values
        ax1.plot(dates, ma50, color='#FF9800', linewidth=1.5, label='MA50')

    ax1.set_title(f'{kode.upper()} — Chart Harian', color='white', fontsize=13, pad=10)
    ax1.tick_params(colors='#888888')
    ax1.set_ylabel('Harga (IDR)', color='#888888')
    for spine in ax1.spines.values():
        spine.set_color('#2a2a4a')
    ax1.grid(color='#2a2a4a', linestyle='--', linewidth=0.5)
    ax1.legend(facecolor='#1a1a2e', labelcolor='white', fontsize=9)

    vol_colors = ['#26a69a' if closes[i] >= opens[i] else '#ef5350' for i in dates]
    ax2.bar(dates, volumes, color=vol_colors, alpha=0.7)
    ax2.set_ylabel('Volume', color='#888888', fontsize=8)
    ax2.tick_params(colors='#888888', labelsize=7)
    for spine in ax2.spines.values():
        spine.set_color('#2a2a4a')
    ax2.grid(color='#2a2a4a', linestyle='--', linewidth=0.5)

    step = max(1, len(hist) // 6)
    tick_positions = dates[::step]
    tick_labels = [hist.index[i].strftime('%d/%m') for i in tick_positions]
    ax1.set_xticks(tick_positions)
    ax1.set_xticklabels(tick_labels, color='#888888', fontsize=8)
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, color='#888888', fontsize=8)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=120, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    buf.seek(0)
    return buf.read()

# ─── HELPER: Analisis dengan Gemini ──────────────────────────────────────────
def analisis_gemini(prompt: str, image_bytes: bytes = None) -> str:
    try:
        if image_bytes:
            image_part = {"mime_type": "image/jpeg", "data": image_bytes}
            response = model.generate_content([prompt, image_part])
        else:
            response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ Error AI: {str(e)}"

# ─── COMMAND: /start ──────────────────────────────────────────────────────────
async def limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(status_request())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pesan = """🤖 *Bot Saham IDX — AI Powered*

Halo! Saya siap bantu analisis saham Indonesia kamu.

📋 *Perintah tersedia:*

📊 `/analisis BBRI` — Analisis teknikal + data saham
🔍 `/screening` — Kandidat saham hari ini
🎯 `/entry BBRI` — Strategi entry, SL & TP
📈 `/chart BBRI` — Chart candlestick
ℹ️ `/info BBRI` — Info dasar emiten
📡 `/limit` — Cek sisa request hari ini

📸 Kirim screenshot chart TradingView → AI langsung analisis!

Contoh: /analisis BBRI atau /entry TLKM"""
    await update.message.reply_text(pesan)

# ─── COMMAND: /analisis ───────────────────────────────────────────────────────
async def analisis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /analisis KODE\nContoh: /analisis BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Menganalisis {kode}...")

    hist, _, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan. Cek kode sahamnya ya.")
        return

    harga_terakhir = hist['Close'].iloc[-1]
    harga_kemarin = hist['Close'].iloc[-2]
    perubahan = ((harga_terakhir - harga_kemarin) / harga_kemarin) * 100
    volume = hist['Volume'].iloc[-1]
    high_1m = hist['High'].max()
    low_1m = hist['Low'].min()
    ma20 = hist['Close'].rolling(20).mean().iloc[-1] if len(hist) >= 20 else harga_terakhir
    ma50 = hist['Close'].rolling(50).mean().iloc[-1] if len(hist) >= 50 else harga_terakhir
    rsi = hitung_rsi(hist['Close'])

    prompt = f"""Kamu adalah analis saham Indonesia yang berpengalaman.
Analisis saham {kode} dengan data berikut:
- Harga terakhir: Rp {harga_terakhir:,.0f}
- Perubahan: {perubahan:+.2f}%
- Volume: {volume:,.0f}
- High periode: Rp {high_1m:,.0f}
- Low periode: Rp {low_1m:,.0f}
- MA20: Rp {ma20:,.0f}
- MA50: Rp {ma50:,.0f}
- RSI (14): {rsi:.1f}

Berikan analisis teknikal singkat dalam Bahasa Indonesia:
1. Kondisi trend saat ini
2. Posisi harga vs MA20 & MA50
3. Interpretasi RSI
4. Kesimpulan (bullish/bearish/sideways)
Format pakai emoji, singkat dan jelas. Maksimal 200 kata."""

    hasil_ai = analisis_gemini(prompt)

    try:
        chart_bytes = buat_chart(kode, hist)
        caption = f"📊 Analisis {kode}\n\n💰 Harga: Rp {harga_terakhir:,.0f} ({perubahan:+.2f}%)\n📦 Volume: {volume:,.0f}\n📈 MA20: Rp {ma20:,.0f}\n📉 MA50: Rp {ma50:,.0f}\n⚡ RSI: {rsi:.1f}\n\n🤖 AI Analysis:\n{hasil_ai}"
        await update.message.reply_photo(photo=chart_bytes, caption=caption[:1024])
    except Exception as e:
        logger.error(f"Chart error: {e}")
        await update.message.reply_text(
            f"📊 Analisis {kode}\n\n💰 Harga: Rp {harga_terakhir:,.0f} ({perubahan:+.2f}%)\n⚡ RSI: {rsi:.1f}\n\n🤖 {hasil_ai}"
        )

# ─── COMMAND: /entry ──────────────────────────────────────────────────────────
async def entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /entry KODE\nContoh: /entry BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Menghitung strategi entry {kode}...")

    hist, _, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan.")
        return

    harga = hist['Close'].iloc[-1]
    low_5d = hist['Low'].tail(5).min()
    high_5d = hist['High'].tail(5).max()
    ma20 = hist['Close'].rolling(20).mean().iloc[-1] if len(hist) >= 20 else harga
    rsi = hitung_rsi(hist['Close'])
    volume_avg = hist['Volume'].tail(20).mean()
    volume_last = hist['Volume'].iloc[-1]
    vol_ratio = (volume_last / volume_avg * 100) if volume_avg > 0 else 100

    prompt = f"""Kamu adalah trader saham Indonesia berpengalaman.
Hitung strategi entry untuk saham {kode}:
- Harga saat ini: Rp {harga:,.0f}
- Low 5 hari: Rp {low_5d:,.0f}
- High 5 hari: Rp {high_5d:,.0f}
- MA20: Rp {ma20:,.0f}
- RSI: {rsi:.1f}
- Volume vs rata-rata: {vol_ratio:.0f}%

Berikan strategi entry trading jangka pendek dalam Bahasa Indonesia:
1. 🎯 Harga entry ideal (range)
2. 🛑 Stop Loss (harga + % dari entry)
3. ✅ Target Profit 1 (konservatif)
4. 🚀 Target Profit 2 (agresif)
5. ⚠️ Catatan risiko
Gunakan angka Rupiah yang spesifik. Format rapi dengan emoji."""

    hasil = analisis_gemini(prompt)
    await update.message.reply_text(f"🎯 Strategi Entry {kode}\n\n{hasil}")

# ─── COMMAND: /screening ──────────────────────────────────────────────────────
async def screening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Screening saham IDX... (butuh ~30 detik)")

    import asyncio
    # Batasi 5 saham saja agar hemat limit API (25/hari)
    kandidat_check = ["BBRI", "BBCA", "BMRI", "TLKM", "ASII"]
    hasil_screening = []

    for kode in kandidat_check:
        await asyncio.sleep(1.5)  # delay 1.5 detik antar request
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
            if harga > ma20 and volume > vol_avg * 1.2 and 40 <= rsi <= 70:
                hasil_screening.append({
                    "kode": kode, "harga": harga,
                    "perubahan": perubahan, "rsi": rsi,
                    "vol_ratio": volume / vol_avg
                })
        except:
            continue

    if not hasil_screening:
        await update.message.reply_text("🔍 Tidak ada kandidat kuat hari ini.\nMarket mungkin sideways atau data terbatas.")
        return

    pesan = f"🔍 Hasil Screening Saham IDX\n{datetime.now().strftime('%d %b %Y')}\n\n"
    for s in hasil_screening[:5]:
        emoji = "🟢" if s['perubahan'] >= 0 else "🔴"
        pesan += f"{emoji} {s['kode']}\n"
        pesan += f"   💰 Rp {s['harga']:,.0f} ({s['perubahan']:+.2f}%)\n"
        pesan += f"   ⚡ RSI: {s['rsi']:.0f} | Vol: {s['vol_ratio']:.1f}x avg\n\n"
    pesan += "Gunakan /analisis KODE untuk analisis lengkap"
    await update.message.reply_text(pesan)

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
            caption=f"📈 Chart {kode}\nHijau=naik | Merah=turun | Biru=MA20 | Oranye=MA50"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal buat chart: {str(e)}")

# ─── COMMAND: /info ───────────────────────────────────────────────────────────
async def info_saham(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Format: /info KODE\nContoh: /info BBRI")
        return

    kode = context.args[0].upper()
    await update.message.reply_text(f"⏳ Mengambil info {kode}...")

    hist, _, ticker = get_stock_data(kode)
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Data {kode} tidak ditemukan.")
        return

    harga = hist['Close'].iloc[-1]
    harga_kemarin = hist['Close'].iloc[-2]
    perubahan = ((harga - harga_kemarin) / harga_kemarin) * 100
    high_1m = hist['High'].max()
    low_1m = hist['Low'].min()
    rsi = hitung_rsi(hist['Close'])

    pesan = f"ℹ️ Info Saham: {kode}\n\n💰 Harga: Rp {harga:,.0f} ({perubahan:+.2f}%)\n📈 High 1 bulan: Rp {high_1m:,.0f}\n📉 Low 1 bulan: Rp {low_1m:,.0f}\n⚡ RSI: {rsi:.1f}\n\nData dari Alpha Vantage"
    await update.message.reply_text(pesan)

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
    await update.message.reply_text(f"🤖 Analisis Chart AI\n\n{hasil}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("limit", limit))
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
    
