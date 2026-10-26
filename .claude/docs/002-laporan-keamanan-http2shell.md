# Laporan Keamanan — HTTP2Shell (CVE-2026-111497) & Isu Sejenis

- **Tanggal audit:** 2026-10-26
- **Cakupan:** `pyproject.toml`, `uv.lock`, `.venv` (Python 3.13.6), seluruh kode `src/`, `main.py`, `set-webhook.sh`, riwayat git
- **Konteks CVE:** HTTP2Shell = out-of-bounds write di decoder Brotli C (`DecodeBlockTypeAndLength()`), Brotli 1.0.3–1.2.0, CVSS 4.0 = 9.2 (crash / RCE). Di PyPI: `Brotli < 1.2.1` dan `brotlicffi < 1.2.1.0`. `requests`/`urllib3`/`httpx`/`aiohttp` otomatis men-decode `Content-Encoding: br` **jika** salah satu paket itu terpasang.

> ⚠️ Repo ini **PUBLIC** di GitHub. Jangan push laporan ini sebelum secret di bagian 3 di-rotate.

---

## 1. Ringkasan

| # | Temuan | Status | Prioritas |
|---|--------|--------|-----------|
| 1 | HTTP2Shell via `Brotli` / `brotlicffi` (PyPI) | **Tidak terdampak** | – |
| 2 | Brotli ter-bundle di PyMuPDF (`libmupdf`) | **Tidak terdampak** (sudah di-patch) | Info |
| 3 | Token bot Telegram + webhook secret ter-push ke repo publik | **Terdampak** | 🔴 Kritis |
| 4 | `.env` (Gemini key + Supabase anon key) ada di riwayat git publik | **Terdampak** | 🟠 Tinggi |
| 5 | Library rentan (certifi, urllib3, tornado, pyjwt, dll.) | Sebagian relevan | 🟡 Sedang |
| 6 | Nama file artifact bertabrakan antar-user | **Terdampak** | 🟡 Sedang |
| 7 | Prompt injection → konten PDF laporan | **Terdampak** | 🟡 Sedang |
| 8 | Tanpa batas pemakaian (biaya Gemini) | **Terdampak** | 🟡 Sedang |
| 9 | `uv.lock` rusak | **Terdampak** | 🟡 Sedang |
| 10 | Isu kode minor (info leak, blocking, dll.) | Terdampak | 🟢 Rendah |

---

## 2. HTTP2Shell (CVE-2026-111497)

### 2.1 Paket `Brotli` / `brotlicffi` — TIDAK TERDAMPAK

**Alasan:**
- Tidak ada `brotli`/`brotlicffi` di `uv.lock` maupun di `.venv`.
- Decoder HTTP client yang aktif hanya `gzip`/`deflate`:
  - `httpx` → `SUPPORTED_DECODERS = ['deflate', 'gzip', 'identity']`, `Accept-Encoding: gzip, deflate`
  - `urllib3` → `ACCEPT_ENCODING = gzip,deflate`
  - Respons `br` dari server jahat tidak akan masuk ke decoder native.
- Jalur inbound: FastAPI/Starlette/uvicorn tidak mendekompresi request body, dan tidak ada middleware dekompresi di `main.py`.

### 2.2 Brotli ter-bundle di PyMuPDF — TIDAK TERDAMPAK (sudah di-patch)

`markdown-pdf` → `pymupdf 1.28.0` → `libmupdf.dylib` mengekspor `BrotliDecoder*` dan `BrotliDecoderVersion()` = **1.2.0** (versi ini masuk rentang rentan). Pip-audit/Dependabot tidak memeriksa library native yang di-bundle seperti ini.

**Alasan aman:**
- MuPDF yang di-bundle adalah **1.29.0**. Fork Brotli di MuPDF ≥ 1.28 sudah memasukkan fix upstream (commit `0ed4268`).
- Sudah diverifikasi: `BrotliDecoderErrorString(-17)` mengembalikan `_ERROR_FORMAT_BLOCK_SWITCH`. Kode error ini baru ditambahkan oleh fix tersebut.
- Aplikasi hanya **membuat** PDF dan tidak pernah membuka PDF dari user, jadi filter `/BrotliDecode` tidak tersentuh.

**Catatan:** scanner yang hanya membaca versi bisa memberi *false positive*. Jangan downgrade ke PyMuPDF/MuPDF 1.27.x.

(`cryptography` juga memuat string "brotli", tapi itu hanya nama algoritma kompresi sertifikat TLS. Tidak ada simbol decoder.)

### 2.3 Ide perbaikan (pencegahan)

```toml
# pyproject.toml — kunci versi minimum jika suatu saat ikut terpasang secara transitif
[tool.uv]
constraint-dependencies = [
  "brotli>=1.2.1",
  "brotlicffi>=1.2.1.0",
  "pymupdf>=1.28.0",
]
```

- Tambahkan `pip-audit` di CI.
- Jika kelak memakai `httpx[brotli]` / `aiohttp`, pastikan versi Brotli sudah patched. Opsi lain: tolak `Content-Encoding: br` sebelum body di-decode.

---

## 3. 🔴 KRITIS — Token bot Telegram ter-push ke repo publik

- **Lokasi:** `set-webhook.sh:1`, commit `809d0f3`. Sudah ada di `origin/main`, `origin/record-webhook`, `origin/feat/contekan-context-window`.
- **Fakta:** token di file itu **sama** dengan `TELEGRAM_BOT_TOKEN` aktif di `.env`. `TELEGRAM_SECRET_TOKEN` aktif juga = `secret123`, yang ikut tertulis di file yang sama.
- **Dampak:** siapa pun bisa:
  - mengambil alih bot (memanggil `setWebhook` ke server miliknya, membaca semua pesan/voice user, mengirim pesan atas nama bot);
  - memalsukan update ke `POST /webhook`, karena secret-nya diketahui.

**Perbaikan:**
1. **Segera** revoke token di @BotFather (`/revoke`), lalu update `.env` dan env di server.
2. Ganti `TELEGRAM_SECRET_TOKEN` dengan nilai acak: `python -c "import secrets;print(secrets.token_urlsafe(32))"`.
3. Ubah `set-webhook.sh` supaya membaca token dari env (`source .env`), bukan hardcode.
4. Bersihkan riwayat git (`git filter-repo`) dan force-push. Tetap anggap token lama sudah bocor.
5. Pasang secret scanning (GitHub Secret Scanning / `gitleaks` pre-commit).

## 4. 🟠 TINGGI — `.env` ada di riwayat git publik

- **Lokasi:** `.env` ter-commit di `9aafda5` (*chore: init*), lalu dihapus di `6493a9d`. Isinya masih bisa diambil dari history.
- **Isi:**
  - `GEMINI_API_KEY` lama (berbeda dari key saat ini);
  - `SUPABASE_KEY` = JWT `role: anon` untuk **project Supabase yang sama** dengan yang dipakai sekarang.
- **Dampak:** jika RLS belum aktif di `chat_histories`/`chat_users`, anon key cukup untuk membaca atau menulis riwayat chat dan data user. Key Gemini lama bisa dipakai (kuota/biaya) jika belum dicabut.

**Perbaikan:**
- Hapus key Gemini lama di Google AI Studio.
- Aktifkan RLS di semua tabel, lalu rotate/nonaktifkan legacy JWT (anon) key di dashboard Supabase.
- Bersihkan riwayat git seperti pada poin 3.

---

## 5. 🟡 Library rentan (hasil `pip-audit` pada `.venv`)

| Paket | Versi | Isu | Relevan? | Alasan | Fix |
|---|---|---|---|---|---|
| `certifi` | 2026.6.17 | PYSEC-2026-4320: root CA emSign dengan intermediate yang kuncinya bocor → MITM TLS | **Ya** | Dipakai `httpx` (Telegram, Supabase, Gemini). Penyerang on-path bisa menyadap bot token & `sb_secret` key | `>=2026.10.19` |
| `urllib3` | 2.7.0 | PYSEC-2026-4176: infinite loop decoder deflate saat streaming (**sejenis**: bug decoder `Content-Encoding`); 4177: buffering chunk-size; 4175: TLS proxy | Rendah | Hanya lewat `requests` (google-genai / markdown-pdf) & `sentry-sdk`, ke host tepercaya, dan streaming API tidak dipakai | `>=2.8.0` |
| `tornado` | 6.5.8 | GHSA-chx6: decompression bomb di curl client (**sejenis**); GHSA-3hv7: DoS query string; GHSA-c2m8: symlink file read | Rendah–Sedang | Server Tornado aktif hanya jika `src/app_webhook.py` (`run_webhook`) dijalankan. Mode utama memakai FastAPI | `>=6.5.9` atau hapus extra `webhooks` |
| `pyjwt` | 2.13.0 | 15 advisory (algorithm confusion, JWKS, ReDoS) | Rendah | Hanya dependensi `supabase-auth`. Aplikasi tidak memverifikasi JWT | `>=2.15.0` |
| `cryptography` | 49.0.0 | PYSEC-2026-3552: oracle PKCS7 decrypt | Tidak | PKCS7 tidak dipakai | `>=50.0.0` |
| `h2` | 4.3.0 | PYSEC-2026-3628: Host header ganda (sisi server) | Tidak | Hanya dipakai sebagai klien HTTP/2 (`httpx[http2]`) | `>=4.4.1` |
| `multidict` | 6.7.1 | PYSEC-2026-4244: memory leak (server aiohttp) | Tidak | `aiohttp` tidak terpasang | `>=6.9.1` |

**Perbaikan:** `uv lock --upgrade-package certifi --upgrade-package urllib3 --upgrade-package tornado --upgrade-package pyjwt --upgrade-package cryptography --upgrade-package h2 --upgrade-package multidict`, lalu `uv sync --locked`.

## 6. 🟡 `uv.lock` rusak (integritas dependensi)

- **Gejala:** `uv export --frozen` gagal dengan pesan *"Dependency `tornado` has missing `source` field but has more than one matching package"*. Entry `pyyaml` terduplikasi, dan `tornado` direferensikan (`python-telegram-bot[webhooks]`) tanpa entry paket. Kemungkinan besar akibat resolusi merge yang salah.
- **Dampak:**
  - scanner berbasis lockfile tidak bisa berjalan;
  - build/deploy bisa me-resolve ulang ke versi yang tidak terkunci;
  - `tornado` terpasang di `.venv` tanpa tercatat di lock.

**Perbaikan:** `uv lock`, commit, lalu gunakan `uv sync --locked` di CI/deploy supaya lock yang tidak sinkron langsung gagal.

---

## 7. Isu kode program

### 7.1 🟡 Nama file artifact bertabrakan antar-user

- **Lokasi:** `src/agents/services.py:28`. `timestamp` dihitung **sekali saat import modul**, lalu dipakai di `:191` (`listening-{timestamp}.wav`) dan `:345` (`laporan-belajar-{timestamp}.pdf`).
- **Dampak:**
  - semua user dalam satu proses mendapat nama file yang sama, sehingga upload kedua gagal (*Duplicate*);
  - jika `upsert` diaktifkan, user B bisa menerima **laporan user A** (kebocoran data);
  - tidak ada prefix per-user, padahal sudah direncanakan di `001-plan-supabase-storage.md`.
- **Perbaikan:** buat nama per request, mis. `f"{user_id}/report-{uuid.uuid4().hex}.pdf"`.

### 7.2 🟡 Prompt injection → konten PDF laporan

- **Lokasi:** `src/agents/services.py:349-350`. `MarkdownPdf()` default `mode="commonmark"` (**`html=True`**) dan `Section(root=".")`.
- **Dampak:** riwayat chat (dikendalikan user) → output LLM → HTML yang diparse native oleh MuPDF. Hasil uji:
  - `<a href="https://evil.example">` ter-embed sebagai link (phishing di PDF resmi);
  - `<img src="file.png">` / `![](file.png)` **menyematkan file gambar dari working dir**;
  - path traversal `../` dan path absolut terblokir.
- **Perbaikan:**
  ```python
  pdf = MarkdownPdf(toc_level=2, mode="js-default")          # html=False, tabel tetap aktif
  pdf.add_section(Section(report_content, root=empty_tmp_dir)) # tidak ada file lokal yang bisa di-embed
  ```
  Tambahkan juga validasi/allowlist domain link jika perlu.

### 7.3 🟡 Tanpa batas pemakaian (cost DoS)

- **Lokasi:** handler di `src/app.py`. Setiap user Telegram bisa memicu Gemini (teks, TTS, upload audio) dan `/report` tanpa batas.
- **Perbaikan:**
  - rate-limit per `user_id`;
  - batasi `update.message.voice.duration` dan panjang teks;
  - opsional: allowlist user terdaftar.

### 7.4 🟢 Rendah

| Lokasi | Isu | Perbaikan |
|---|---|---|
| `src/app.py:187` | `error_handler` mengirim `context.error` mentah ke user (bocor detail internal Supabase/Gemini) | Kirim pesan generik ke user; detail cukup di log |
| `src/app_webhook.py:18-20` | Bot token ditulis ke log (`webhook_url/{TOKEN}`) | Hapus token dari log; pakai `secret_token` |
| `main.py:89` | Secret dibandingkan dengan `!=` (tidak constant-time) | `hmac.compare_digest(...)` |
| `src/agents/services.py:298`, semua handler | `time.sleep(5)` dan SDK sinkron di dalam handler async → satu request membekukan event loop | `asyncio.to_thread(...)` atau `client.aio` |
| `src/app.py:152-165` | File voice user di `temp/` tidak terhapus jika terjadi error | Bungkus dengan `try/finally` |
| `main.py:69-82` | Endpoint uji `/`, `/get`, `/post` dan `/docs` terbuka di production | Hapus endpoint uji; `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` |

---

## 8. Urutan perbaikan

1. Revoke token bot dan ganti webhook secret (poin 3). **Hari ini.**
2. Revoke key Gemini lama, cek RLS Supabase, rotate anon key (poin 4).
3. Bersihkan riwayat git dan pasang secret scanning.
4. Perbaiki `uv.lock`, upgrade `certifi`/`urllib3`/`tornado`/dll., tambahkan `constraint-dependencies` Brotli.
5. Perbaiki penamaan artifact (7.1) dan render PDF (7.2).
6. Rate-limit dan perbaikan minor (7.3, 7.4).

## 9. Cara verifikasi ulang

```bash
grep -i brotli uv.lock                                   # harus kosong / >=1.2.1
uv pip freeze | uvx pip-audit -r /dev/stdin --no-deps --disable-pip
.venv/bin/python -c "import ctypes,os,pymupdf;l=ctypes.CDLL(os.path.join(os.path.dirname(pymupdf.__file__),'libmupdf.dylib'));f=l.BrotliDecoderErrorString;f.restype=ctypes.c_char_p;print(f(-17))"
# patched  -> b'_ERROR_FORMAT_BLOCK_SWITCH'   |   rentan -> b'_ERROR_UNKNOWN'
gitleaks git .                                           # cek secret di seluruh riwayat
```

## Referensi

- [Aikido — Python packages vulnerable to Node2Shell/HTTP2Shell](https://www.aikido.dev/blog/python-packages-vulnerable-node2shell-brotli-cve-2026-111497)
- [DEV — HTTP2Shell: pip-audit missed Brotli](https://dev.to/alanwest/http2shell-cve-2026-111497-pip-audit-missed-brotli-how-to-check-your-stack-31e3)
- [Phoenix Security — HTTP2Shell expansion (bundled copies, MuPDF)](https://phoenix.security/http2shell-expansion-cve-2026-111497-brotli-bundled-copies/)
- [Debian Security Tracker — CVE-2026-111497](https://security-tracker.debian.org/tracker/CVE-2026-111497)
