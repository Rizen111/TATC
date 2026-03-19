# 🤖 Bot Saham IDX — Panduan Deploy

## File yang ada di folder ini:
- `bot.py` → kode utama bot
- `requirements.txt` → daftar library yang dibutuhkan
- `railway.toml` → konfigurasi Railway

---

## 📋 Langkah Deploy ke Railway

### Step 1 — Upload ke GitHub
1. Buka **github.com** → login / daftar (gratis)
2. Klik tombol **"New repository"** (tombol hijau)
3. Nama repo: `saham-bot`
4. Klik **"Create repository"**
5. Klik **"uploading an existing file"**
6. Upload ketiga file: `bot.py`, `requirements.txt`, `railway.toml`
7. Klik **"Commit changes"**

### Step 2 — Deploy di Railway
1. Buka **railway.app** → login pakai GitHub
2. Klik **"New Project"**
3. Pilih **"Deploy from GitHub repo"**
4. Pilih repo `saham-bot` kamu
5. Klik **"Deploy Now"**

### Step 3 — Isi Environment Variables
Di Railway, klik project kamu → tab **"Variables"** → tambahkan:

| Variable | Value |
|---|---|
| `TELEGRAM_TOKEN` | Token bot dari BotFather |
| `GEMINI_API_KEY` | API Key dari Google AI Studio |

Klik **"Deploy"** lagi setelah isi variables.

### Step 4 — Test Bot
Buka Telegram → cari username bot kamu → ketik `/start`

---

## 🎮 Perintah Bot

| Perintah | Fungsi |
|---|---|
| `/start` | Menu utama |
| `/analisis BBRI` | Analisis teknikal + chart |
| `/screening` | Cari kandidat saham hari ini |
| `/entry BBRI` | Strategi entry, SL & TP |
| `/chart BBRI` | Chart candlestick 1 bulan |
| `/info BBRI` | Info dasar emiten |
| Kirim foto | Analisis screenshot TradingView |

---

## ⚠️ Catatan Penting
- Ganti `TELEGRAM_TOKEN` dan `GEMINI_API_KEY` di Railway Variables
- JANGAN taruh API key langsung di file bot.py
- Railway gratis 500 jam/bulan → cukup untuk pemakaian pribadi
