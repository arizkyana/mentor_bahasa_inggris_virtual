# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Tentang Proyek

Bot Telegram "Mentor Bahasa Inggris Virtual" — mentor belajar bahasa Inggris untuk pengguna Indonesia, ditenagai Gemini. Seluruh kode, komentar, prompt agent, dan balasan ke pengguna ditulis dalam Bahasa Indonesia. Ikuti konvensi ini saat menambah kode baru.

Proyek ini merupakan materi studi kasus dari kelas Belajar Python Agentic AI di wpucourse.id (https://wpucourse.id/course/belajar-python-agentic-ai)

## Perintah

Manajemen dependensi memakai **uv** (Python >= 3.13).

```bash
uv sync                              # install dependensi

uv run fastapi dev main.py           # mode webhook (dev, auto-reload)
uv run fastapi run main.py           # mode webhook (produksi)
uv run python main.pooling.py        # mode long-polling (tanpa webhook publik)

uv run fastapi deploy                # deploy ke FastAPI Cloud
```

Belum ada test suite, linter, maupun formatter yang dikonfigurasi di `pyproject.toml`.

**Deployment**: `.github/workflows/deploy.yml` menjalankan `uv run fastapi deploy` ke FastAPI Cloud setiap push ke branch `main`. Butuh secrets `FASTAPI_CLOUD_TOKEN` dan `FASTAPI_CLOUD_APP_ID`.

**_catatan_**:
branch `feat/file-handling-with-supabase-storage` yang sekarang digunakan hanya untuk riset file handling dengan supabase storage. Riset ini **belum selesai**: `supabase_client = supabase.get_supabase_client()` sudah dibuat di level modul `main.py` dan `src/agents/services.py`, tapi belum dipakai — pemanggilan `storage.create_bucket(...)` dan `storage.from_("output").upload(...)` di `listening_exercise` masih dalam bentuk komentar. Artinya alur file saat ini tetap sepenuhnya lokal (lihat bagian Artifacts).

## Environment Variables

`src/core/env.py` memvalidasi **semua** env var saat import dan langsung `raise RuntimeError` bila ada yang kosong. Efeknya: import modul apa pun yang menyentuh `env` akan gagal total kalau `.env` belum lengkap, ini sering jadi penyebab error saat menjalankan file secara terpisah.

Var yang wajib ada: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_MODEL_TTS`, `SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_SECRET_TOKEN`, `BOT_HOST`, `BOT_PORT`.

## Arsitektur

Alur berlapis, satu arah:

```
main.py / main.pooling.py     entrypoint (webhook FastAPI / polling)
  → src/app.py                handler Telegram + layer pengiriman
    → src/agents/lead.py      LeadAgent — orkestrator function calling
      → src/agents/services.py  tools & sub-agent (satu fungsi = satu agent)
        → src/core/*          env, llm, supabase, prompts, artifacts, schemas, format
          → src/repository/   akses tabel Supabase
```

### Dua entrypoint, satu set handler

`main.py` adalah aplikasi FastAPI: membangun `Application` python-telegram-bot, mendaftarkan handler dari `src/app.py`, lalu `set_webhook` di `lifespan` dengan `secret_token=env.TELEGRAM_SECRET_TOKEN`. Endpoint `POST /webhook/{TELEGRAM_BOT_TOKEN}` memverifikasi header `X-Telegram-Bot-Api-Secret-Token` terhadap env var yang sama sebelum memproses update. Ada juga `GET /health-check`.

`main.pooling.py` memanggil `src/app.py:run()` yang membangun `Application`-nya sendiri, mendaftarkan handler yang sama, **plus** `job_queue.run_daily` untuk `task_reminder` jam 08:00 WIB, lalu `run_polling()`. Reminder harian ini **tidak** aktif di mode webhook.

`src/app_cli.py` (REPL terminal) dan `src/app_webhook.py` (webhook bawaan PTB) adalah sisa eksperimen dan tidak dipakai oleh entrypoint mana pun.

### Pola agent: fungsi Python sebagai tool Gemini

`LeadAgent` (`src/agents/lead.py`) mendaftarkan fungsi Python langsung sebagai `tools` ke Gemini dan mengandalkan automatic function calling. Hanya tiga fungsi yang terdaftar sebagai tool: `skill_type_classification`, `evaluate_writing`, `get_learning_tip`.

**Docstring fungsi adalah deskripsi tool yang dibaca Gemini.** Mengubah docstring di `services.py` berarti mengubah perilaku routing agent, perlakukan sebagai bagian dari prompt, bukan sekadar dokumentasi.

Sub-agent lain dipanggil berantai, bukan langsung oleh model: `skill_type_classification` mengklasifikasikan pesan jadi salah satu dari reading/speaking/listening/writing, lalu `generate_exercise` mendelegasikan ke `*_exercise` yang sesuai. `evaluate_speaking` dan `generate_report` dipanggil langsung dari handler (`handle_voice`, `report_command`), tidak lewat function calling.

### System prompt sebagai file Markdown

Setiap agent punya instruksi di `src/agents/instructions/agent-*.md`, dimuat dengan `prompts.load_instruction("agent-lead")` (nama file tanpa ekstensi, di-cache `lru_cache`). Untuk mengubah perilaku agent, edit Markdown-nya — jangan hardcode prompt di `services.py`.

### Structured output

Skema Pydantic di `src/core/schemas.py` dipakai lewat pola berulang:

```python
config=types.GenerateContentConfig(response_json_schema=SomeSchema.model_json_schema())
data = SomeSchema.model_validate(json.loads(response.text))
```

### Artifacts: jalur samping untuk file

Function calling Gemini hanya bisa mengembalikan teks, jadi file (audio listening, PDF laporan) dikirim lewat "keranjang" `contextvars` di `src/core/artifacts.py`:

1. `LeadAgent.handle_send_message` memanggil `artifacts.start()` di awal setiap request.
2. Service seperti `listening_exercise` memanggil `artifacts.add(path, kind, caption)` setelah menulis file ke `src/output/`.
3. `LeadAgent` memanggil `artifacts.collect()` setelah generate selesai, mencatat tiap artifact ke Supabase, dan mengembalikannya bersama teks.
4. `src/app.py:_send_artifact` mengirim file ke Telegram sesuai `kind` (audio/video/document) lalu **menghapus file lokal**.

Konsekuensi: file di `src/output/` bersifat sementara dan hilang setelah terkirim. `src/output/` dan `src/temp/` ada di `.gitignore`.

### Persistensi (Supabase)

Semua akses DB lewat `ChatRepository` (`src/repository/chat_repository.py`). Dua tabel:

- `chat_histories` — `user_id`, `role` (`"user"` | `"model"`, mengikuti konvensi Gemini), `message_text`, `artifact` (nullable), `created_at`
- `chat_users` — `user_id`, `username`, `chat_id`

`LeadAgent._load_history` memuat **seluruh** riwayat user dan mengubahnya ke `list[types.Content]` pada setiap pesan masuk — tanpa windowing atau ringkasan, jadi konteks tumbuh tanpa batas seiring pemakaian.

Klien Gemini dan Supabase di-cache singleton lewat `@lru_cache` di `src/core/llm.py` dan `src/core/supabase.py`. Selalu ambil lewat fungsi getter tersebut, jangan bikin klien baru.

### Format balasan Telegram

Bot memakai `ParseMode.MARKDOWN_V2` sebagai default. **Setiap teks yang dikirim ke Telegram harus melewati `to_telegram_markdown()`** (`src/core/format.py`) — output Markdown mentah dari LLM akan ditolak Telegram karena karakter yang belum di-escape.

Timezone di seluruh aplikasi: `Asia/Jakarta` (WIB).

### Listening exercise (alur multi-model)

`listening_exercise` merangkai tiga langkah (nama file audio memakai `timestamp` yang dihitung di dalam fungsi, sama seperti `generate_report` untuk PDF): generate script dialog dua penutur (`GEMINI_MODEL`, terstruktur via `ListeningExerciseSchema`) → generate audio multi-speaker (`GEMINI_MODEL_TTS`, suara `Puck` untuk speaker satu dan `Kore` untuk speaker dua) → tulis PCM ke file `.wav` → daftarkan sebagai artifact. Teks balasan hanya memuat daftar pertanyaan; `agent-lead.md` secara eksplisit melarang model menuliskan ulang transkrip.

### Voice note

`handle_voice` mengunduh `.ogg` ke `src/temp/`, meng-upload ke Gemini Files API, mem-polling status `PROCESSING` tiap 5 detik, lalu menghapus file lokal setelah evaluasi selesai.

## Inkonsistensi yang sudah ada di kode

Beberapa hal berikut sudah rusak di kondisi saat ini, jangan bingung mengiranya sebagai perubahan yang Anda sebabkan:

- `src/app_cli.py:29` memperlakukan `response["artifacts"]` sebagai objek Supabase (`.data`), padahal `artifacts.collect()` mengembalikan `list[dict]`. File ini memang sisa eksperimen dan tidak dipakai entrypoint mana pun.
