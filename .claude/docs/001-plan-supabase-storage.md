---
description: Memindahkan artifact (audio listening & laporan PDF) dari filesystem lokal ke Supabase Storage sebagai system-of-record
argument-hint: "[kode task, mis. T4 atau 'Batch B']"
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# 001 — File Handling dengan Supabase Storage

|                     |                                            |
| ------------------- | ------------------------------------------ |
| **Status**          | Disetujui, siap dieksekusi                 |
| **Branch**          | `feat/file-handling-with-supabase-storage` |
| **Eksekutor**       | agent `software-developer`                 |
| **Dependency baru** | Tidak ada                                  |
| **Migration DDL**   | Tidak ada                                  |

---

## 1. Konteks & Masalah

Branch `feat/file-handling-with-supabase-storage` dibuat untuk riset file handling, tapi berhenti di tahap
"klien di-instansiasi, pemanggilan API masih komentar" (`services.py:182`, `services.py:199-200`).
Alur file saat ini **100% lokal**.

**Koreksi atas premis awal:** `speaking_exercise` (`services.py:64-79`) **tidak menghasilkan file apa pun** —
murni teks. Hanya dua fungsi yang menyentuh disk:

| File                         | Dibuat di         | Lokasi        | Nasib sekarang                                   |
| ---------------------------- | ----------------- | ------------- | ------------------------------------------------ |
| `listening-<ts>.wav`         | `services.py:187` | `src/output/` | dikirim → `os.remove` (`app.py:108`)             |
| `laporan-belajar-<ts>.pdf`   | `services.py:343` | `src/output/` | dikirim (`app.py:75`) → **tidak pernah dihapus** |
| `<file_id>.ogg` (voice user) | `app.py:146`      | `src/temp/`   | upload ke Gemini Files → dihapus (`app.py:157`)  |

### Apakah implementasi sekarang sudah best-practice?

Pola _write → stream → delete_ dalam satu request itu **normal di industri** — bukan anti-pattern.
Yang bermasalah adalah hal lain:

1. **Dangling pointer (defect utama).** `chat_repository.save_artifact()` (`chat_repository.py:49-57`)
   menyimpan **path filesystem lokal** ke kolom `chat_histories.artifact`, padahal file itu dihapus
   beberapa milidetik kemudian. Nilai di DB **invalid sejak detik pesan terkirim**. Akibatnya
   `get_last_artifact_by_user_id()` (`chat_repository.py:59-70`) jadi dead code yang tidak mungkin dipakai.
2. **PDF laporan bocor.** Tidak ada `os.remove` di `report_command`, sehingga `src/output/*.pdf`
   menumpuk di container ephemeral.
3. **Menulis ke dalam source tree.** `env.OUTPUT_DIR = src/output` (`env.py:12`). Konvensinya `tempfile`
   / OS temp dir; banyak PaaS mem-mount direktori app read-only.
4. **`app.py:132` hanya mengirim `artifacts[0]`**, sisanya dibuang meski sudah tercatat di DB (`lead.py:69`).
5. `os.remove` tidak di `try/finally` (`app.py:108`, `app.py:157`) → file menumpuk saat pengiriman gagal.
6. `_send_artifact` mencatat "artifact tidak ditemukan" (`app.py:91-92`) lalu **tetap lanjut** `open()` → `FileNotFoundError`.

**Kesimpulan:** masalahnya bukan "lokal vs cloud", tapi **tidak ada system-of-record untuk file**.
Kolom `artifact` sudah dirancang untuk menunjuk sebuah file, tapi tidak pernah menunjuk apa pun yang valid.

### Keputusan bisnis yang sudah dikonfirmasi

| Pertanyaan       | Jawaban                                                                         |
| ---------------- | ------------------------------------------------------------------------------- |
| System of record | **Supabase Storage**                                                            |
| Scope file       | Audio listening `.wav` + laporan `.pdf` (**voice note peserta TIDAK disimpan**) |
| Akses bucket     | **Private + signed URL**                                                        |
| Retensi          | **Permanen** (review saat mendekati kuota)                                      |

---

## 2. Keputusan Arsitektur

### AD-1 — Supabase Storage sebagai system-of-record, kolom `artifact` menyimpan **object key**

Kolom `artifact` diisi object key (mis. `123456789/listening/20260813-101500-123456.wav`),
**bukan signed URL** dan **bukan path lokal**.

_Alternatif yang ditolak:_

- **Telegram `file_id` sebagai persistensi.** Setelah `reply_audio`, PTB mengembalikan `Message.audio.file_id`;
  kirim ulang cukup `reply_audio(audio=file_id)` — nol infra, nol biaya, nol egress. Ini sebenarnya solusi
  **termurah** untuk memperbaiki dangling pointer. **Ditolak** karena mengunci artifact ke satu channel:
  tidak bisa dipakai web dashboard, tidak bisa dibaca service lain, retensinya di luar kendali kita.
- **Menyimpan signed URL di kolom `artifact`.** **Ditolak keras** — signed URL punya masa berlaku, jadi
  kita hanya mengganti dangling pointer lokal dengan dangling pointer yang expired. Signed URL adalah
  nilai turunan yang dihitung _on demand_ dari object key, bukan data yang disimpan.

### AD-2 — Nol filesystem: seluruh artifact hidup di memori sebagai `bytes`

`src/output/` dihapus dari alur. Sudah diverifikasi ke library yang terpasang:

| Kebutuhan            | API                                          | Status                                |
| -------------------- | -------------------------------------------- | ------------------------------------- |
| Tulis WAV ke buffer  | `wave.open(BytesIO(), "wb")`                 | stdlib, menerima file-like            |
| Render PDF ke buffer | `MarkdownPdf.save_bytes(BytesIO)`            | ada di `markdown_pdf/__init__.py:156` |
| Upload               | `storage.from_(b).upload(path, file: bytes)` | `storage3/_sync/file_api.py:574-579`  |
| Kirim ke Telegram    | `InputFile(obj: bytes, filename=...)`        | `telegram/_files/inputfile.py:96-104` |

_Alternatif yang ditolak:_

- **Tetap tulis ke disk lalu upload.** Lebih sedikit perubahan, tapi mempertahankan seluruh kelas bug
  yang sedang kita perbaiki (`os.remove` tanpa `try/finally`, kebocoran PDF, source tree writable).
- **Pakai `tempfile.NamedTemporaryFile`.** Lebih rapi dari `src/output/`, tapi tetap butuh disk padahal
  library-nya sudah mendukung buffer. Menambah langkah tanpa menambah nilai.

### AD-3 — Bytes dibawa di dalam `Artifact`, tidak di-download ulang untuk pengiriman

`Artifact` membawa field `content: bytes` untuk request berjalan. `_send_artifact` mengirim dari
bytes yang sudah ada di tangan.

_Alternatif yang ditolak:_

- **`_send_artifact` men-download ulang dari Storage lewat object key.** Membuat satu jalur pengiriman
  yang seragam untuk artifact baru maupun kirim-ulang dari riwayat. **Ditolak untuk sekarang** karena
  fitur kirim-ulang belum ada di scope — men-download byte yang baru saja kita upload adalah
  pemborosan round-trip + egress murni (speculative generality).
  Saat fitur kirim-ulang dibangun nanti, cukup jadikan `content` opsional dengan fallback `storage.download()`.

> **Konsekuensi wajib:** `lead.py:78` (`logger.debug(f"handle_send_message: {artifacts_data}")`) akan
> men-dump megabyte binary ke log. Baris ini **harus** diubah agar hanya mencatat `object_path`.

### AD-4 — Bucket dibuat manual sekali di dashboard, bukan `create_bucket()` saat runtime

Draft komentar di `services.py:182` memanggil `storage.create_bucket("output")` di dalam alur request.

_Alternatif yang ditolak:_

- **`create_bucket` idempotent saat startup.** Terlihat praktis, tapi menuntut privilege tinggi setiap
  boot dan **menyembunyikan config drift** — bucket yang salah nama akan dibuat diam-diam alih-alih gagal keras.
- **`create_bucket` di dalam request.** Satu panggilan network sia-sia per latihan listening.

Bucket bernama `artifacts` (private) dibuat sekali lewat dashboard Supabase; aplikasi berasumsi bucket sudah ada
dan gagal keras kalau tidak.

### AD-5 — Modul baru `src/core/storage.py`

Konsisten dengan pola `src/core/*` yang sudah ada (`env`, `llm`, `supabase`, `prompts`, `artifacts`, `format`).
`supabase.py` tetap **hanya** factory klien; `storage.py` yang memegang urusan domain object storage.
Tidak masuk `src/repository/` karena folder itu khusus akses **tabel**.

_Alternatif yang ditolak:_

- **Panggil `supabase_client.storage...` langsung dari `services.py`.** Lebih sedikit file, tapi menyebarkan
  detail bucket & konvensi object key ke seluruh service — persis yang sudah mulai terjadi di
  `services.py:27` + `main.py:41` (dua klien module-level yang tidak dipakai siapa pun).

### AD-6 — Konvensi object key: `{user_id}/{category}/{timestamp}.{ext}`

Contoh: `123456789/listening/20260813-101500-123456.wav`, `123456789/report/20260813-101500-123456.pdf`

Prefix per-user memberi tiga hal sekaligus: namespace anti-collision, dasar RLS di masa depan
(`(storage.foldername(name))[1]`), dan retensi/audit per-prefix.
`user_id` Telegram bukan rahasia dan bucket-nya private, jadi aman dipakai sebagai prefix.

---

## 3. Dampak ke Modul & Schema

### Database — **tidak ada migration**

- Kolom `chat_histories.artifact` (text, nullable) **sudah ada**. Yang berubah hanya **semantik isinya**:
  path lokal → object key. Tidak ada perubahan DDL.
- **Data lama:** baris `artifact` yang sudah ada berisi path lokal absolut yang memang sudah mati.
  Dibiarkan apa adanya (tidak merusak apa pun karena tidak ada yang membacanya). Pembersihan opsional
  dijadikan T9 dan **dijalankan manual oleh pemilik project**, bukan oleh agent.
- **Index:** _belum diperlukan untuk scope ini._ `get_last_artifact_by_user_id` masih dead code —
  index baru ditambahkan saat fitur kirim-ulang dibangun, yaitu
  `(user_id, created_at DESC) WHERE artifact IS NOT NULL`. Menambahnya sekarang = index yang tidak pernah dipakai.
- **N+1 / `SELECT *`:** tidak ada regresi. `load_history_by_user_id` sudah `select("role","message_text")`
  sehingga kolom `artifact` (teks panjang) **tidak** ikut terbaca setiap pesan. Pertahankan ini.
- **Debt yang ditemukan (di luar scope, jangan dikerjakan di sini):** `load_history_by_user_id` membaca
  **seluruh** riwayat user setiap pesan masuk tanpa windowing (`lead.py:36-44`) dan tabelnya belum punya
  index `(user_id, created_at)`. Ini akan jadi hotspot jauh sebelum storage jadi masalah.

### Perkiraan volume

- WAV 24 kHz / 16-bit / mono = **48 KB per detik**. Dialog 30–60 detik → **1,4–2,9 MB per latihan**.
- PDF laporan lewat `save_bytes` **tidak terkompresi** (`do_compress = 0`) → perkiraan 100–500 KB.
- Skala kelas 50 peserta aktif × 10 latihan listening ≈ **1 GB** → **menyentuh batas free tier Supabase (1 GB)**.
- Skala demo 20 peserta × 5 latihan ≈ 200 MB → aman.

Retensi permanen diterima untuk skala kelas, dengan **trigger review di 500 MB**. Tuas mitigasi termurah
saat itu: **perpendek durasi dialog lewat `src/agents/instructions/agent-generate-script.md`** — mengecilkan
file tanpa satu baris kode pun dan tanpa dependency baru (kompresi ke MP3/OGG butuh ffmpeg/pydub → ditolak sekarang).

### Modul yang berubah

| File                                | Perubahan                                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| `src/core/env.py`                   | + `SUPABASE_BUCKET`; hapus `OUTPUT_DIR` di akhir rangkaian                                        |
| `.env.example`                      | + `SUPABASE_BUCKET=`                                                                              |
| `src/core/storage.py`               | **baru**                                                                                          |
| `src/core/artifacts.py`             | `Artifact` TypedDict diganti                                                                      |
| `src/agents/services.py`            | `listening_exercise`, `_write_wave_file`, `generate_report`; hapus `supabase_client` module-level |
| `src/agents/lead.py`                | `save_artifact` pakai object key; perbaiki `logger.debug`                                         |
| `src/repository/chat_repository.py` | signature `save_artifact`                                                                         |
| `src/app.py`                        | `_send_artifact`, `handle_text`, `report_command`                                                 |
| `main.py`                           | hapus `supabase_client` module-level yang tidak dipakai                                           |
| `CLAUDE.md`                         | perbarui bagian Artifacts, Persistensi & Environment Variables                                    |

### Keamanan

`SUPABASE_KEY` di project ini berformat `sb_secret_*` — setara **service_role**, artinya **bypass RLS**.
Konsekuensinya: bucket private bisa langsung dipakai **tanpa policy tambahan**, tapi key ini
**tidak boleh pernah sampai ke sisi klien**. Catat eksplisit di `CLAUDE.md`: kalau suatu saat memakai key
`sb_publishable_*`, storage policy per-prefix menjadi wajib.

---

## 4. Rencana Task Berurutan

Diurutkan menurut ketergantungan teknis. Batch = satuan yang aman di-deploy.

### Batch A — Fondasi (aditif, tanpa perubahan perilaku, bisa di-deploy sendiri)

#### T1 — Konfigurasi bucket

- `src/core/env.py`: tambah `SUPABASE_BUCKET = _required_env("SUPABASE_BUCKET")` di dekat `SUPABASE_KEY` (baris 31-32).
- `.env.example`: tambah `SUPABASE_BUCKET=` di blok Supabase.
- `CLAUDE.md` bagian _Environment Variables_: tambahkan `SUPABASE_BUCKET` ke daftar var wajib +
  catatan bahwa bucket **private** bernama sama harus dibuat manual di dashboard Supabase lebih dulu.
- ⚠️ Ingat `env.py` melakukan validasi saat import — tanpa var ini seluruh aplikasi gagal start.

#### T2 — Modul `src/core/storage.py` (baru)

- Pakai `supabase.get_supabase_client()` yang sudah ada (`src/core/supabase.py:8`). **Jangan** bikin klien baru.
- Skeleton (bukan kode final, sesuaikan saat implementasi):

  ```python
  import src.core.env as env
  import src.core.supabase as supabase
  from datetime import datetime

  def build_object_path(user_id: int, category: str, extension: str) -> str:
      """Bangun object key: {user_id}/{category}/{timestamp}.{extension}"""
      timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
      return f"{user_id}/{category}/{timestamp}.{extension}"

  def upload(object_path: str, content: bytes, content_type: str) -> str:
      """Unggah bytes ke bucket, kembalikan object key."""
      client = supabase.get_supabase_client()
      client.storage.from_(env.SUPABASE_BUCKET).upload(
          path=object_path,
          file=content,
          file_options={"content-type": content_type, "upsert": "false"},
      )
      return object_path

  def create_signed_url(object_path: str, expires_in: int = 3600) -> str:
      """URL bertanda tangan untuk akses sementara (belum dipakai di scope ini)."""

  def download(object_path: str) -> bytes:
      """Ambil kembali isi object (belum dipakai di scope ini)."""
  ```

- `create_signed_url` & `download` **boleh ditulis sekarang** karena keduanya primitif storage satu baris,
  bukan layer spekulatif — tapi jangan dipanggil dari mana pun di batch ini.

### Batch B — Alur audio listening (atomik: T3–T7 harus mendarat bersama)

> Batch ini mengubah kontrak `Artifact`. Deploy sebagian akan merusak pengiriman audio.

#### T3 — Ubah kontrak `Artifact` di `src/core/artifacts.py`

- Ganti TypedDict (baris 5-8) menjadi:
  ```python
  class Artifact(TypedDict):
      object_path: str          # key di Supabase Storage
      filename: str             # nama file yang dilihat peserta di Telegram
      kind: str                 # "audio" | "document"
      caption: Optional[str]
      content: bytes            # isi file untuk request berjalan; TIDAK disimpan ke DB
  ```
- Sesuaikan signature `add()` (baris 21-27). Hapus field `path` sepenuhnya.
- Ini sekaligus menutup ketidaksesuaian tipe yang ada sekarang: `path` dideklarasikan `str`
  tapi `services.py:206` mengisinya dengan `pathlib.Path`.

#### T4 — `listening_exercise` upload ke Storage (`src/agents/services.py:180-221`)

- `_write_wave_file` (baris 166-177): ganti parameter `audio_output_path: Path` → objek file-like,
  supaya bisa menulis ke `io.BytesIO()`.
- Hapus `env.OUTPUT_DIR.mkdir(...)` (baris 185) dan `audio_output_path` (baris 187).
- Alur baru: tulis WAV ke `BytesIO` → `buffer.getvalue()` → `storage.build_object_path(user_id, "listening", "wav")`
  → `storage.upload(..., content_type="audio/wav")` → `artifacts.add(object_path=..., filename=..., kind="audio", caption=..., content=...)`.
- Hapus dua blok komentar Supabase (baris 182, 199-202) dan `supabase_client` module-level (baris 27) +
  import-nya (baris 10) bila sudah tidak dipakai.
- **Masalah `user_id`:** `listening_exercise` dipanggil Gemini lewat automatic function calling dan
  **tidak menerima `user_id`**. Menambah parameter `user_id` ke signature akan membuat Gemini
  ikut mengisinya — **jangan**, karena docstring/signature adalah bagian dari prompt.
  Solusinya konsisten dengan pola yang sudah ada di project: **simpan `user_id` di `contextvars`**,
  sejajar dengan `artifacts` (`src/core/artifacts.py`). Tambahkan ContextVar `current_user_id`
  (di-set di `LeadAgent.handle_send_message` bersamaan dengan `artifacts.start()` di `lead.py:55`).
- Sekalian perbaiki bug string tergabung di baris 218-221 (`"...terlampir otomatis"` + `"Pertanyaan:"`
  menempel jadi `otomatisPertanyaan:`) — tambahkan `\n`.

#### T5 — `chat_repository.save_artifact` menyimpan object key (`src/repository/chat_repository.py:49-57`)

- Signature: `save_artifact(self, user_id: int, object_path: str, kind: str = "audio")`.
- Hapus `str(artifact_path)`; simpan `object_path` apa adanya.
- `message_text` jangan lagi hardcode `"[audio]"` (baris 54) — turunkan dari `kind` (mis. `f"[{kind}]"`),
  karena nilai ini ikut terbaca `LeadAgent._load_history` sebagai konteks Gemini.

#### T6 — `LeadAgent` meneruskan object key (`src/agents/lead.py`)

- Baris 55: set ContextVar `user_id` berdampingan dengan `artifacts.start()`.
- Baris 69-72: `save_artifact(user_id=user_id, object_path=item["object_path"], kind=item["kind"])`.
- Baris 78: ubah log agar **hanya** mencatat `object_path` — jangan pernah memformat dict yang berisi `content: bytes`.

#### T7 — Pengiriman dari bytes (`src/app.py`)

- `_send_artifact` (baris 84-109): buang `os.path.exists`, `open(...)`, dan `os.remove(...)`.
  Kirim `InputFile(artifact["content"], filename=artifact["filename"])` ke
  `reply_audio` / `reply_video` / `reply_document`.
- `handle_text` (baris 129-133): **loop seluruh** `response["artifacts"]`, bukan hanya index 0.
  Hapus baris komentar mati 130 dan `logger.debug` baris 131 (isinya kini mengandung bytes).
- Cek apakah `import os` (baris 3) masih dipakai setelah perubahan.

### Batch C — Laporan PDF (independen dari Batch B, boleh menyusul)

#### T8 — `generate_report` ke Storage (`src/agents/services.py:316-351` + `src/app.py:60-81`)

- Ganti `pdf.save(report_file_path)` (baris 347) → `pdf.save_bytes(buffer)` dengan `buffer = io.BytesIO()`.
- Hapus `env.OUTPUT_DIR.mkdir(...)` (baris 342) dan `report_file_path` (baris 343).
- Upload dengan `content_type="application/pdf"`, category `"report"`.
- `generate_report` mengembalikan dict `{"object_path", "filename", "content"}` alih-alih string path;
  `lead.handle_report` (baris 113-126) meneruskannya; `report_command` (baris 75-81) mengirim dari bytes.
- Catat juga ke DB lewat `save_artifact(..., kind="document")` — sekarang laporan sama sekali tidak tercatat.
- ✅ Ini sekaligus menutup **kebocoran PDF** yang selama ini tidak pernah dihapus.
- ⚠️ Verifikasi ukuran output: `save_bytes` mematikan kompresi. Kalau PDF membengkak tak wajar,
  fallback-nya `pdf.save()` ke `tempfile.NamedTemporaryFile` lalu baca bytes-nya.

### Batch D — Pembersihan & dokumentasi

#### T9 — Bersihkan sisa jalur lokal

- `src/core/env.py`: hapus `OUTPUT_DIR` (baris 12) setelah dipastikan tidak ada referensi tersisa
  (`grep -rn "OUTPUT_DIR" src`). **`TEMP` tetap ada** — masih dipakai voice note (`app.py:144-146`).
- `main.py`: hapus `supabase_client = supabase.get_supabase_client()` (baris 41) + import-nya bila menganggur.
- `.gitignore`: pattern `output` boleh dihapus, `temp` **dipertahankan**.
- `CLAUDE.md` bagian _Artifacts_: tulis ulang alurnya (kini in-memory + Storage, bukan `src/output/`),
  dan bagian _Persistensi_ untuk menjelaskan kolom `artifact` = object key.
  Hapus juga catatan "riset belum selesai" di baris 30.
- **Manual (bukan tugas agent), opsional:** bersihkan path mati di data lama —
  `UPDATE chat_histories SET artifact = NULL WHERE artifact LIKE '/%';`
  Jalankan sendiri lewat SQL editor Supabase setelah Batch B live.

### Di luar scope (backlog berikutnya, jangan dikerjakan sekarang)

- Fitur kirim-ulang artifact dari riwayat (`get_last_artifact_by_user_id` + `storage.download`/`create_signed_url`)
  — inilah yang membuat `create_signed_url` berguna, plus index `(user_id, created_at DESC) WHERE artifact IS NOT NULL`.
- Menyimpan voice note peserta (ditolak eksplisit di scope ini karena beban privasi).
- Windowing/ringkasan riwayat chat di `lead.py:_load_history`.
- Memindahkan pemanggilan sync yang memblokir event loop ke thread — lihat Risiko R1.

---

## 5. Risiko & Mitigasi

| #      | Risiko                                                                                                                                                                                                                                                                                                                               | Dampak                                                                                                                                                                        | Mitigasi                                                                                                                                                                                                |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **R1** | **`contextvars` pecah kalau kode dipindah ke thread.** `handle_send_message` (`lead.py:46`) & `handle_report` adalah panggilan **sync blocking** di dalam handler async — inilah yang saat ini membuat `artifacts` (dan nanti ContextVar `user_id`) berada di context yang sama. Upload Storage menambah durasi blocking event loop. | Kalau ada yang "memperbaiki" ini dengan `run_in_executor`/`asyncio.to_thread`, artifact **hilang diam-diam** (`artifacts.add` no-op saat bucket `None`, `artifacts.py:24-25`) | **Jangan** ubah ke thread di plan ini. Tulis komentar peringatan di `src/core/artifacts.py` bahwa perpindahan thread wajib memakai `contextvars.copy_context()`. Perbaikan blocking = backlog terpisah. |
| **R2** | Upload gagal (network/kuota) setelah TTS berhasil                                                                                                                                                                                                                                                                                    | Peserta kehilangan audio padahal biaya Gemini TTS sudah keluar                                                                                                                | Bungkus upload di `try/except`; saat gagal, tetap kirim audio ke Telegram dari bytes yang sudah di tangan dan simpan `artifact = NULL`. **Kegagalan arsip tidak boleh menggagalkan pengiriman.**        |
| **R3** | Kuota storage free tier 1 GB terlampaui (retensi permanen)                                                                                                                                                                                                                                                                           | Upload mulai ditolak                                                                                                                                                          | Trigger review di **500 MB**. Tuas pertama: perpendek dialog lewat `agent-generate-script.md` (nol kode, nol dependency).                                                                               |
| **R4** | Bucket belum dibuat / salah nama saat deploy                                                                                                                                                                                                                                                                                         | Semua latihan listening gagal                                                                                                                                                 | Bucket dibuat manual sebelum Batch B live; dokumentasikan di `CLAUDE.md`. Gagal keras dengan pesan jelas, jangan auto-create (AD-4).                                                                    |
| **R5** | `SUPABASE_KEY` = `sb_secret_*` (bypass RLS) bocor                                                                                                                                                                                                                                                                                    | Akses penuh ke DB & Storage                                                                                                                                                   | Server-side only. Catat di `CLAUDE.md`. Jangan pernah kirim key/signed URL lewat kanal publik.                                                                                                          |
| **R6** | `SUPABASE_BUCKET` belum di-set di FastAPI Cloud                                                                                                                                                                                                                                                                                      | **Aplikasi gagal start total** (`env.py` validasi saat import)                                                                                                                | Set secret di environment FastAPI Cloud **sebelum** merge T1.                                                                                                                                           |
| **R7** | Memori naik: bytes artifact ditahan sepanjang request                                                                                                                                                                                                                                                                                | Beberapa MB per request bersamaan                                                                                                                                             | Batas wajar (WAV 1,4–2,9 MB). Pantau; kalau jadi masalah, barulah pindah ke pola download-saat-kirim (alternatif di AD-3).                                                                              |
| **R8** | `logger.debug` men-dump binary ke log                                                                                                                                                                                                                                                                                                | Log membengkak / tidak terbaca                                                                                                                                                | T6 & T7 secara eksplisit membereskan `lead.py:78` dan `app.py:131`.                                                                                                                                     |

---

## 6. Verifikasi

Dijalankan oleh pemilik project (agent tidak menjalankan perintah yang mengubah state):

1. **Prasyarat:** bucket private `artifacts` sudah ada di dashboard Supabase; `SUPABASE_BUCKET` terisi di `.env`.
2. `uv run fastapi dev main.py` → cek `GET /health-check` mengembalikan `{"status": "OK"}`
   (membuktikan validasi `env.py` lolos setelah T1).
3. **Batch B:** kirim `"buatkan latihan listening"` ke bot →
   - audio `.wav` diterima di Telegram dan bisa diputar;
   - object muncul di bucket dengan key `{user_id}/listening/<timestamp>.wav`;
   - baris `chat_histories` terbaru punya `artifact` = object key yang sama (bukan path `/Users/...`);
   - `ls src/output` → **tidak ada file baru** (idealnya folder tidak terbentuk lagi);
   - log tidak memuat binary.
4. **Multi-artifact:** pancing satu request yang menghasilkan lebih dari satu artifact → pastikan
   semuanya terkirim, bukan hanya yang pertama (regresi `app.py:132`).
5. **Batch C:** `/report` → PDF diterima, terbuka normal, ukurannya wajar; object ada di
   `{user_id}/report/...pdf`; `src/output/` tetap kosong (bukti kebocoran PDF tertutup).
6. **Jalur negatif:** ganti sementara `SUPABASE_BUCKET` ke nama yang tidak ada → pastikan audio
   **tetap terkirim** ke peserta dan `artifact` tersimpan `NULL` (membuktikan R2).
7. **Regresi voice note:** kirim voice note → evaluasi speaking tetap jalan dan `src/temp/` bersih
   setelahnya (jalur ini sengaja tidak diubah).

---

## 7. Definition of Done

- [ ] Bucket private `artifacts` ada; `SUPABASE_BUCKET` terdaftar di `env.py`, `.env.example`, dan environment FastAPI Cloud.
- [ ] `src/core/storage.py` ada dan **satu-satunya** tempat yang menyentuh `client.storage`.
- [ ] Audio listening & laporan PDF terunggah ke Storage dengan key `{user_id}/{category}/{timestamp}.{ext}`.
- [ ] `chat_histories.artifact` berisi **object key**, bukan path lokal dan bukan signed URL — diverifikasi langsung di tabel.
- [ ] **Tidak ada file baru yang ditulis ke `src/output/`**; `env.OUTPUT_DIR` sudah dihapus; `src/temp/` (voice note) tidak tersentuh.
- [ ] Seluruh artifact dalam satu response terkirim, bukan hanya `artifacts[0]`.
- [ ] Kegagalan upload tidak menggagalkan pengiriman ke peserta (R2 terbukti lewat verifikasi #6).
- [ ] Tidak ada `bytes` yang masuk ke log maupun ke kolom database.
- [ ] Tidak ada dependency baru di `pyproject.toml` dan tidak ada migration DDL.
- [ ] `CLAUDE.md` (bagian Artifacts, Persistensi, Environment Variables) diperbarui; catatan "riset belum selesai" di baris 30 dihapus.
