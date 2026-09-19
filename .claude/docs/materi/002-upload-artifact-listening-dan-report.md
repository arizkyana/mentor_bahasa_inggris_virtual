# 002 — Menyambungkan Supabase Storage ke `listening_exercise` dan `generate_report`

## Audiens dan Prasyarat

Lanjutan dari `001-supabase-storage-dasar.md`. Diasumsikan kamu sudah:

- punya bucket `mentor-artifacts` yang private
- pernah upload file, membuat signed URL, dan menghapus objek lewat `scripts/coba_storage.py`
- tahu bahwa object key bukan path filesystem, dan tahu kenapa `"rb"` wajib

Kalau tiga hal itu belum, kerjakan materi 001 dulu. Materi ini tidak mengulangnya.

Versi library: `supabase`/`storage3` **2.31.0**, `python-telegram-bot` **22.8**, `google-genai` **2.11.0**, `fastapi` **0.141.1**, Python **3.13**.

Di materi ini kamu akan mengubah **tujuh file** di kode bot. Commit dulu pekerjaanmu yang sekarang sebelum mulai.

## Learning Objectives

Setelah menyelesaikan materi ini, peserta dapat:

1. **Menjelaskan** (C2) alur artifact berbasis `contextvars` dari `services.py` sampai terkirim ke Telegram, dan alasan pola ini dipilih.
2. **Menerapkan** (C3) modul `src/core/storage.py` lalu menyambungkannya ke jalur artifact sehingga audio listening tersimpan permanen.
3. **Menerapkan** (C3) jalur artifact untuk `generate_report`, sehingga PDF laporan melewati mekanisme pengiriman yang sama dengan audio.
4. **Menganalisis** (C4) empat mode gagal pada jalur file yang ada sekarang dan menelusuri pemicunya sampai ke baris kode.
5. **Mengevaluasi** (C5) pilihan bucket private + object key di database dibanding public URL dan `telegram_file_id`, termasuk konsekuensi `SUPABASE_KEY` yang bypass RLS.

Materi ini mulai dari C2 dan bermuara di C5. Satu latihan C6 disediakan sebagai tugas mandiri di luar jam sesi.

## Outline dan Alokasi Waktu

| Waktu | Bagian |
| --- | --- |
| 10' | Bedah alur artifact yang sudah ada |
| 10' | Env var dan bucket yang bisa dibuat ulang |
| 20' | `src/core/storage.py`, dan keputusan di mana upload dipanggil |
| 15' | Menyambungkan dua penghasil file |
| 10' | Merapikan layer pengiriman |
| 10' | Analisis mode gagal |
| 10' | Keamanan dan biaya |
| 5' | Yang sengaja tidak dikerjakan |
| **90'** | **Total** |

---

## 1. Bedah Alur Artifact yang Sudah Ada

Sebelum mengubah apa pun, kamu harus bisa menceritakan alur yang sekarang. Kalau tidak, perubahanmu cuma tebak-tebakan.

### Kenapa jalur artifact ini ada

`LeadAgent` memakai automatic function calling Gemini: fungsi Python didaftarkan langsung sebagai `tools`, Gemini yang memutuskan kapan memanggilnya. Masalahnya, **function calling hanya bisa mengembalikan teks**. Tidak ada mekanisme untuk mengembalikan file dari sebuah tool.

Jadi file dikirim lewat jalur samping. `src/core/artifacts.py` menyediakan "keranjang" per-request memakai `contextvars`:

```
src/agents/lead.py:55       artifacts.start()      -> keranjang kosong dibuat
src/agents/services.py:205  artifacts.add(...)     -> service menaruh file ke keranjang
src/agents/lead.py:66       artifacts.collect()    -> isi keranjang diambil
src/app.py:84               _send_artifact(...)    -> file dikirim ke Telegram, lalu dihapus
```

Kenapa `contextvars` dan bukan variabel global biasa? Karena bot ini melayani banyak update secara bersamaan. Variabel global akan tercampur antar user — audio milik user A bisa terkirim ke user B. `contextvars` memberi setiap konteks eksekusi salinan nilainya sendiri, jadi keranjang milik A tidak terlihat oleh B.

### Ketimpangan yang harus kamu lihat sekarang

Sekarang buka `src/agents/services.py:316-351` dan `src/agents/lead.py:101-126`. `generate_report` **tidak melewati jalur artifact sama sekali**. Ia mengembalikan path mentah, lalu `report_command` di `src/app.py:75-81` membuka file itu sendiri:

```python
    with open(report_file_path, "rb") as report_pdf:
        await update.message.reply_document(...)
```

Perhatikan: tidak ada `os.remove` di situ. **PDF laporan tidak pernah dihapus.** Setiap `/report` meninggalkan satu file di `src/output/`.

Jadi proyek ini punya dua penghasil file dengan dua perlakuan berbeda. Menyeragamkannya adalah setengah dari pekerjaan hari ini.

### Satu detail kecil yang perlu kamu ketahui

Lihat `src/core/artifacts.py:5-8`:

```python
class Artifact(TypedDict):
    path: str
    kind: str
    caption: Optional[str]
```

`path` dideklarasikan `str`. Tapi `services.py:206` mengisinya dengan objek `Path`:

```python
    artifacts.add(path=audio_output_path, ...)   # audio_output_path adalah Path
```

Tidak ada error, karena `TypedDict` **tidak divalidasi saat runtime** — ia hanya petunjuk untuk type checker. Kode berikutnya tetap jalan karena `open()` dan `os.path.exists()` menerima keduanya. Kita akan menulis kode baru yang aman untuk dua-duanya dengan `Path(item["path"])`.

## 2. Env Var dan Bucket yang Bisa Dibuat Ulang

### Langkah 2.1 — nama bucket jadi env var

Di materi 001 nama bucket ditulis langsung di script. Untuk kode aplikasi itu tidak layak: setiap peserta punya nama bucket berbeda, dan nilai seperti ini tidak boleh ikut ter-commit.

`src/core/env.py`, tambahkan satu baris setelah `SUPABASE_KEY`:

```python
SUPABASE_URL = _required_env("SUPABASE_URL")
SUPABASE_KEY = _required_env("SUPABASE_KEY")
SUPABASE_BUCKET = _required_env("SUPABASE_BUCKET")
```

`.env.example`, tambahkan barisnya juga supaya peserta lain tahu var ini wajib:

```
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_BUCKET=
```

**Sekarang jalankan bot sebelum mengisi `.env`.** Sengaja.

```bash
uv run python main.pooling.py
```

```
RuntimeError: env variabel `SUPABASE_BUCKET` belum di-set
```

Bot tidak jalan sama sekali — bukan gagal saat fitur listening dipakai, tapi gagal saat modul di-import. Ini konsekuensi pola fail-fast di `src/core/env.py:16-24`, dan itu memang disengaja: lebih baik aplikasi menolak start daripada jalan setengah lalu gagal di depan pengguna.

Harga yang harus kamu bayar: setiap peserta yang menarik perubahan ini akan mendapat bot yang mati sampai mereka menambah satu baris di `.env`. Umumkan.

Sekarang isi `.env`:

```
SUPABASE_BUCKET=mentor-artifacts
```

### Langkah 2.2 — bucket yang bisa dibuat berulang tanpa error

Di materi 001 kamu membuat bucket lewat dashboard. Itu tidak bisa diulang oleh 50 peserta lain secara konsisten. Kita ganti dengan script.

Buat `scripts/init_storage.py`:

```python
import src.core.env as env
import src.core.supabase as supabase

from loguru import logger

OPSI_BUCKET = {
    "public": False,
    "file_size_limit": 20 * 1024 * 1024,  # 20 MB
    "allowed_mime_types": ["audio/wav", "application/pdf"],
}


def main():
    client = supabase.get_supabase_client()
    daftar_bucket = [bucket.id for bucket in client.storage.list_buckets()]

    if env.SUPABASE_BUCKET in daftar_bucket:
        client.storage.update_bucket(env.SUPABASE_BUCKET, options=OPSI_BUCKET)
        logger.info(f"bucket `{env.SUPABASE_BUCKET}` sudah ada, opsinya disamakan")
        return

    client.storage.create_bucket(env.SUPABASE_BUCKET, options=OPSI_BUCKET)
    logger.success(f"bucket `{env.SUPABASE_BUCKET}` dibuat")


if __name__ == "__main__":
    main()
```

```bash
uv run python -m scripts.init_storage
```

Jalankan **dua kali**. Kali kedua harus tetap sukses, hanya pesannya berubah. Script yang aman dijalankan berulang seperti ini disebut **idempoten**, dan itu syarat wajib untuk apa pun yang masuk ke pipeline deployment.

Sekarang bandingkan dengan kode yang masih menganggur di `src/agents/services.py:182`:

```python
    # supabase_client.storage.create_bucket("output")
```

Baris itu ada **di dalam** `listening_exercise` — artinya dijalankan setiap kali peserta minta latihan listening. Kalau komentarnya dibuka, latihan listening pertama berhasil, latihan kedua dan seterusnya gagal dengan 409. Provisioning tidak boleh berada di jalur request. Hapus baris komentar itu.

Dua opsi baru yang kita pasang lewat script punya konsekuensi yang harus kamu sadari:

- `file_size_limit` 20 MB — audio WAV 1 menit sekitar 2,75 MB (perhitungannya di bagian 7), jadi 20 MB memberi ruang untuk audio panjang. Kalau suatu saat ada file lebih besar, upload akan ditolak, bukan diam-diam terpotong.
- `allowed_mime_types` hanya `audio/wav` dan `application/pdf` — ini pertahanan berlapis. Kalau ada bug yang membuat content-type salah, uploadnya ditolak di sisi server. Efek sampingnya: kalau kamu punya objek `.txt` sisa latihan materi 001 di bucket yang sama, upload `.txt` berikutnya akan ditolak. Itu memang yang kita mau.

## 3. `src/core/storage.py`, dan Keputusan Di Mana Upload Dipanggil

### Langkah 3.1 — modul storage

Buat `src/core/storage.py`:

```python
import uuid

import src.core.env as env
import src.core.supabase as supabase

from pathlib import Path
from loguru import logger
from storage3.exceptions import StorageApiError

# tanpa ini, storage3 memberi semua objek content-type text/plain
CONTENT_TYPE = {
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
}


def build_object_key(kind: str, user_id: int, suffix: str) -> str:
    """Susun object key unik, contoh: audio/100918936/9f3c1a....wav"""

    return f"{kind}/{user_id}/{uuid.uuid4().hex}{suffix}"


def upload_file(local_path: Path, object_key: str) -> str | None:
    """Upload file lokal ke bucket. Kembalikan object key, atau None kalau gagal."""

    client = supabase.get_supabase_client()
    content_type = CONTENT_TYPE.get(local_path.suffix, "application/octet-stream")

    try:
        with open(local_path, "rb") as berkas:
            client.storage.from_(env.SUPABASE_BUCKET).upload(
                path=object_key,
                file=berkas,
                file_options={"content-type": content_type},
            )
    except (StorageApiError, OSError) as error:
        # gagal upload tidak boleh membatalkan balasan ke peserta
        logger.error(f"gagal upload {object_key}: {error}")
        return None

    logger.success(f"upload berhasil: {object_key}")

    return object_key


def create_signed_url(object_key: str, expires_in: int = 3600) -> str | None:
    client = supabase.get_supabase_client()
    hasil = client.storage.from_(env.SUPABASE_BUCKET).create_signed_url(
        path=object_key, expires_in=expires_in
    )

    # storage3 2.31 mengembalikan kunci yang sama dengan dua ejaan
    return hasil.get("signedURL") or hasil.get("signedUrl")


def remove(object_keys: list[str]):
    client = supabase.get_supabase_client()

    return client.storage.from_(env.SUPABASE_BUCKET).remove(object_keys)
```

Empat hal yang sengaja dibuat begini:

**Klien diambil lewat `supabase.get_supabase_client()`, bukan dibuat baru.** Fungsi itu di-cache dengan `@lru_cache` (`src/core/supabase.py:7`), jadi seluruh aplikasi berbagi satu koneksi. Membuat klien baru di sini akan membuang manfaat cache tersebut.

**`build_object_key` memakai `uuid4`, bukan nama file asli.** Dengan `uuid`, dua peserta yang memicu latihan pada milidetik yang sama tidak akan tabrakan, dan kamu tidak perlu `upsert` sama sekali. `user_id` diselipkan di key supaya nanti bisa "hapus semua milik user ini" dan supaya isi bucket bisa dibaca manusia saat debugging.

**`upload_file` mengembalikan `None` saat gagal, bukan melempar exception.** Ini keputusan produk, bukan sekadar gaya kode: kalau Supabase sedang down, peserta tetap harus menerima audio latihannya di Telegram. Arsip boleh gagal; layanan tidak. Konsekuensinya, pemanggil **wajib** mengecek nilai kembaliannya — kalau lupa, kamu akan menyimpan `None` ke database tanpa sadar.

**`create_signed_url` membaca dua ejaan kunci.** Ini bukan paranoia; `storage3` 2.31 memang mengembalikan `signedURL` dan `signedUrl` sekaligus, dan kita tidak tahu yang mana yang bertahan di versi berikutnya.

Verifikasi cepat sebelum lanjut:

```bash
uv run python -c "import src.core.storage; print('modul storage siap')"
```

Kalau `SUPABASE_BUCKET` belum ada di `.env`, perintah ini gagal. Itu perilaku yang diharapkan.

### Langkah 3.2 — di mana upload dipanggil? (keputusan desain)

Ini bagian yang paling mudah dijawab asal, dan paling mahal kalau salah. Kita punya tiga tempat yang mungkin.

**Opsi A — upload di dalam `listening_exercise` dan `generate_report`.**
Paling intuitif: file dibuat di situ, ya di-upload di situ juga. Tapi object key kita butuh `user_id`, dan `user_id` **tidak tersedia di sana**. `listening_exercise` dipanggil berantai dari `skill_type_classification` yang merupakan tool terdaftar — signature-nya dibaca Gemini sebagai deskripsi tool. Menambah parameter `user_id` ke rantai itu berarti Gemini akan mencoba mengisinya sendiri dengan angka karangan.

**Opsi B — simpan `user_id` di `contextvars` juga, lalu upload tetap di `services.py`.**
Secara teknis jalan dan konsisten dengan pola `artifacts.py`. Tapi ia menambah satu state implisit lagi, dan membuat `services.py` — yang tugasnya memanggil model — jadi ikut tahu soal bucket dan object key.

**Opsi C — upload di `LeadAgent`, setelah `artifacts.collect()`.**
`LeadAgent` sudah memegang `user_id` di semua handler-nya, dan sudah punya loop yang mencatat artifact ke database (`lead.py:69-72`). Satu tempat untuk semua jenis artifact, sekarang dan nanti.

**Kita pilih Opsi C.** Alasan utamanya `user_id` tersedia tanpa mengotori signature tool, dan penambahan penghasil file berikutnya (misalnya latihan reading berbentuk PDF) otomatis ikut ter-upload tanpa mengubah `storage.py` maupun `services.py`.

Harga yang kita bayar, dan ini harus kamu sadari:

- Upload jadi **tidak terlihat** dari `listening_exercise`. Orang yang membaca fungsi itu tidak akan tahu filenya berakhir di Supabase. Ini dibayar dengan komentar dan dokumentasi, dan itu memang pertahanan yang lemah.
- Kalau suatu hari ada artifact yang **tidak boleh** diarsipkan, `_persist_artifacts` harus tahu pengecualiannya — kita perlu menambah penanda di `Artifact`.
- Jarak antara "file dibuat" dan "file di-upload" jadi lebih jauh, sehingga saat debugging kamu harus melompat antar file.

## 4. Menyambungkan Dua Penghasil File

### Langkah 4.1 — `Artifact` menampung object key

`src/core/artifacts.py`:

```python
class Artifact(TypedDict):
    path: str
    kind: str  # "audio" | "document"
    caption: Optional[str]
    object_key: Optional[str]  # lokasi di Supabase Storage, None kalau upload gagal


def add(
    path: str,
    kind: str = "audio",
    caption: Optional[str] = None,
    object_key: Optional[str] = None,
) -> None:
    """Catat satu artifact untuk dikirim oleh layer pengiriman (CLI/Telegram)"""
    bucket = _artifacts.get()
    if bucket is None:
        return

    bucket.append(
        {"path": path, "kind": kind, "caption": caption, "object_key": object_key}
    )
```

Parameter baru diberi default `None` supaya semua pemanggil lama tetap jalan tanpa diubah.

### Langkah 4.2 — `listening_exercise` dibersihkan

Fungsi ini sebenarnya sudah benar. Yang perlu dilakukan cuma membuang kode mati. `src/agents/services.py`, hapus baris komentar `create_bucket` dan blok `with open(...)` yang salah:

```python
def listening_exercise(text: str):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    env.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_output_path = env.OUTPUT_DIR / f"listening-{timestamp}.wav"

    # 1. "model" untuk generate script percakapan dua orang
    generate_script = _listening_generate_script(text=text)

    # 2. "model" untuk generate audio berdasarkan `generate_script`
    audio = _listening_generate_audio_script(generate_script=generate_script)

    # 3. generate wave file
    _write_wave_file(audio_output_path, audio)

    # 4. catat ke jalur artifact — upload ke Storage dilakukan di LeadAgent
    artifacts.add(
        path=audio_output_path,
        kind="audio",
        caption="dengarkan audio latihan listening ini, lalu jawab pertanyaannya.",
    )
    ...
```

Sekalian hapus dua baris yang tidak terpakai di bagian atas file:

```python
import src.core.supabase as supabase     # hapus
supabase_client = supabase.get_supabase_client()   # hapus, baris 27
```

dan yang serupa di `main.py:41`. Keduanya sisa riset yang tidak pernah dipakai; sekarang akses Storage sudah punya rumahnya sendiri di `src/core/storage.py`.

File lokal **tetap** ditulis ke `src/output/`. Kita perlu file nyata di disk karena `MarkdownPdf.save()` hanya menerima path (bukan buffer memori), dan menyeragamkan dua jalur lebih mudah dibaca daripada satu in-memory satu file. `src/output/` aman untuk ini karena filenya hanya hidup di dalam satu request.

### Langkah 4.3 — `generate_report` masuk ke jalur yang sama

`src/agents/services.py`, ganti ekor fungsi `generate_report`:

```python
    pdf = MarkdownPdf(toc_level=2)
    pdf.add_section(Section(report_content))
    pdf.save(report_file_path)

    # daftarkan ke jalur artifact, sama seperti audio listening
    artifacts.add(
        path=report_file_path,
        kind="document",
        caption=f"Laporan belajar bahasa inggris {start_date} - {end_date}",
    )

    logger.success("success generate report")
```

Baris `return str(report_file_path)` dibuang. Mulai sekarang path tidak lagi mengalir keluar lewat nilai kembalian, melainkan lewat keranjang artifact.

### Langkah 4.4 — `LeadAgent` melakukan upload

`src/agents/lead.py`, tambahkan import:

```python
import src.core.storage as storage

from pathlib import Path
```

Tambahkan satu method:

```python
    def _persist_artifacts(self, user_id: int) -> list[artifacts.Artifact]:
        """Upload artifact request ini ke Storage, lalu catat object key-nya ke database."""

        hasil: list[artifacts.Artifact] = []

        for item in artifacts.collect():
            local_path = Path(item["path"])

            object_key = storage.upload_file(
                local_path=local_path,
                object_key=storage.build_object_key(
                    kind=item["kind"], user_id=user_id, suffix=local_path.suffix
                ),
            )

            item["object_key"] = object_key

            if object_key:
                self.chat_repository.save_artifact(
                    user_id=user_id, object_key=object_key, kind=item["kind"]
                )

            hasil.append(item)

        return hasil
```

Di `handle_send_message`, ganti blok `artifacts.collect()` dan loop `save_artifact` (baris 66-72) dengan satu baris:

```python
        answer = response.text
        artifacts_data = self._persist_artifacts(user_id=user_id)

        self.chat_repository.save_message(
            role="model", user_id=user_id, message_text=answer
        )

        return {"text": answer, "artifacts": artifacts_data}
```

Di `handle_report`, tambahkan `artifacts.start()` dan ganti nilai kembaliannya:

```python
    def handle_report(
        self, user_id: int, username: str, start_date: str, end_date: str
    ):
        logger.info("[handle_report]")

        self.chat_repository.save_message(
            user_id=user_id,
            role="user",
            message_text=f"[generate learning report: {start_date} - {end_date}]",
        )

        history = self._load_history(user_id=user_id)

        artifacts.start()  # keranjang artifact untuk request ini

        services.generate_report(
            conversation_history=history,
            start_date=start_date,
            end_date=end_date,
            username=username,
        )

        self.chat_repository.save_message(
            user_id=user_id,
            role="model",
            message_text=f"[generate learning report: {start_date} - {end_date} sudah selesai dicetak]",
        )

        return self._persist_artifacts(user_id=user_id)
```

`artifacts.start()` di sini bukan formalitas. Tanpa itu, `_artifacts.get()` mengembalikan `None` dan `artifacts.add()` di `generate_report` akan **diam-diam tidak melakukan apa-apa** (lihat `artifacts.py:23-25`). PDF tetap dibuat, tapi tidak pernah terkirim, dan tidak ada satu pun error di log. Ini jenis bug yang paling menyebalkan karena tidak berisik.

### Langkah 4.5 — kolom `artifact` diisi object key

`src/repository/chat_repository.py`:

```python
    def save_artifact(self, user_id: int, object_key: str, kind: str = "audio"):
        self.supabase.table("chat_histories").insert(
            {
                "user_id": user_id,
                "role": "model",
                "message_text": f"[{kind}]",
                "artifact": object_key,
            }
        ).execute()
```

**Tidak ada migrasi skema.** Kolom `artifact` sudah bertipe `text` dan nullable; yang berubah hanya jenis nilai yang kita masukkan. Baris-baris lama yang berisi path lokal absolut sengaja dibiarkan — nanti jadi bahan Latihan 4.

## 5. Merapikan Layer Pengiriman

Bagian ini tidak menyentuh Storage sama sekali, tapi tanpanya pekerjaan tadi tidak akan terlihat hasilnya untuk fitur report.

`src/app.py`, `_send_artifact`:

```python
async def _send_artifact(update: Update, artifact: Artifact):
    artifact_path = artifact.get("path")
    kind = artifact.get("kind")
    caption = artifact.get("caption")

    if not os.path.exists(artifact_path):
        logger.warning(f"artifact tidak ditemukan: {artifact_path}")
        return  # dulu tidak ada return, alurnya lanjut lalu open() melempar error

    safe_caption_text = to_telegram_markdown(caption) if caption else None

    try:
        with open(artifact_path, "rb") as artifact_file:
            if kind == "audio":
                await update.message.reply_audio(
                    audio=artifact_file, caption=safe_caption_text
                )
            elif kind == "video":
                await update.message.reply_video(
                    video=artifact_file, caption=safe_caption_text
                )
            else:
                await update.message.reply_document(
                    document=artifact_file, caption=safe_caption_text
                )
    finally:
        os.remove(artifact_path)
        logger.info(f"file lokal dihapus: {artifact_path}")
```

Tiga perubahan, masing-masing menutup satu mode gagal:

1. `return` setelah `logger.warning`. Kode lama hanya mencatat peringatan lalu tetap lanjut ke `open()`, yang pasti melempar `FileNotFoundError`.
2. `try/finally`. Kalau `reply_audio` gagal karena timeout Telegram, file lokal tetap terhapus. Sekarang aman karena arsipnya sudah ada di Storage.
3. `caption` boleh `None`. `to_telegram_markdown(None)` melempar `AttributeError: 'NoneType' object has no attribute 'split'` — coba sendiri kalau tidak percaya.

`handle_text`, ganti pengiriman satu artifact jadi semua artifact:

```python
    for artifact in response["artifacts"]:
        await _send_artifact(update, artifact)
```

Kode lama (`app.py:129-133`) hanya menyentuh `response["artifacts"][0]`. Artifact kedua dan seterusnya tidak pernah terkirim **dan tidak pernah terhapus**. Sekarang belum ada request yang menghasilkan dua artifact, tapi itu kondisi sementara, bukan jaminan.

`report_command` sekarang memakai jalur yang sama:

```python
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        to_telegram_markdown("laporan sedang kami buat, mohon tunggu...")
    )

    user_id = update.message.from_user.id
    username = update.message.from_user.username

    end_date = date.today()
    start_date = end_date - timedelta(days=7)

    laporan_artifacts = lead_agent.handle_report(
        user_id=user_id, username=username, start_date=start_date, end_date=end_date
    )

    for artifact in laporan_artifacts:
        await _send_artifact(update, artifact)
```

Blok `with open(report_file_path, "rb")` yang lama dibuang seluruhnya. Kebocoran PDF tertutup di sini, bukan karena kita menambah `os.remove`, tapi karena PDF sekarang lewat fungsi yang memang sudah mengurus penghapusan.

Terakhir, `handle_voice` (`app.py:157`) punya penyakit yang sama — `os.remove(str(voice_file_path))` di akhir fungsi tanpa `try/finally`. Kalau `lead_agent.handle_send_voice` melempar exception, file `.ogg` tertinggal di `src/temp/`. Bungkus dengan `try/finally`.

## 6. Analisis Mode Gagal (C4)

Sekarang kamu sudah memperbaikinya. Bagian ini melatih kemampuan menemukannya sendiri lain kali.

Untuk setiap skenario, jawab: **file mana yang tertinggal atau tidak terkirim, dan baris mana penyebabnya di kode sebelum perbaikan?**

| # | Skenario | Petunjuk lokasi |
| --- | --- | --- |
| 1 | Satu request menghasilkan dua artifact | `app.py:129-133` |
| 2 | Peserta menjalankan `/report` sepuluh kali | `app.py:75-81` |
| 3 | `reply_audio` gagal karena koneksi Telegram timeout | `app.py:94-108` |
| 4 | File lokal terhapus proses lain sebelum `_send_artifact` sempat jalan | `app.py:91-94` |
| 5 | `generate_report` memanggil `artifacts.add()` tanpa `artifacts.start()` lebih dulu | `artifacts.py:23-25` |

Skenario 5 punya sifat yang berbeda dari empat lainnya, dan itulah yang membuatnya berbahaya. Empat yang pertama meninggalkan jejak: file menumpuk, atau ada traceback di log. Skenario 5 tidak meninggalkan apa-apa — `add()` langsung `return` saat keranjangnya `None`. Kalau kamu lupa `artifacts.start()` di Langkah 4.4, gejalanya cuma "PDF-nya kok tidak muncul ya", tanpa satu pun baris error untuk dilacak.

Bukti bahwa masalah ini nyata, bukan teoretis — jalankan ini:

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()
hasil = (
    client.table('chat_histories')
    .select('created_at, artifact')
    .not_.is_('artifact', 'null')
    .order('created_at', desc=True)
    .limit(5)
    .execute()
)

for baris in hasil.data:
    nilai = baris['artifact']
    jenis = 'path lokal (basi)' if nilai.startswith('/') else 'object key'
    print(f\"{baris['created_at']} | {jenis:18} | {nilai[:60]}\"
)
"
```

Setelah kamu menjalankan bot dengan perubahan hari ini, tabel yang sama akan berisi dua jenis nilai bercampur: baris lama berisi path lokal yang filenya sudah lama hilang, baris baru berisi object key yang objeknya benar-benar ada. Data lama yang tidak kompatibel adalah konsekuensi normal dari perubahan semantik kolom, dan kode apa pun yang membaca kolom itu nanti harus siap menghadapi keduanya.

## 7. Keamanan dan Biaya (C5)

### Kenapa bucket private, padahal RLS tidak dipakai

Cek format kunci Supabase-mu:

```bash
uv run python -c "
import src.core.env as env
print(env.SUPABASE_KEY[:11] + '...', '| panjang:', len(env.SUPABASE_KEY))
"
```

Kalau berawalan `sb_secret_`, itu **secret key** — setara `service_role`, dan ia **bypass Row Level Security**. Artinya semua kebijakan RLS yang kamu tulis di Supabase tidak berlaku untuk koneksi ini. Kunci seperti ini tidak boleh muncul di klien mana pun yang bisa dibaca pengguna: tidak di aplikasi mobile, tidak di frontend, tidak di repositori publik.

Lalu kenapa kita tidak memakai RLS untuk melindungi artifact? Karena RLS bekerja berdasarkan `auth.uid()` dari Supabase Auth, sedangkan pengguna bot ini teridentifikasi lewat `user_id` Telegram. Mereka bukan user Supabase. Kebijakan RLS berbasis auth memang tidak punya pijakan di sini.

Jadi pertahanan kita bertumpu pada dua hal lain:

1. **Bucket private.** Tanpa kredensial, object key sebanyak apa pun tidak bisa diunduh. Ini kenapa mengaktifkan "Public bucket" akan langsung membatalkan seluruh model keamanan ini — semua orang yang menebak object key bisa mengunduh rekaman dan laporan belajar peserta.
2. **Object key yang tidak bisa ditebak.** `uuid4().hex` memberi 128 bit keacakan.

Pertanyaan diskusi (C5), jawab bersama kelompok: **kalau bot ini nanti punya dashboard web, apakah pola sekarang masih cukup?** Pertimbangkan bahwa dashboard berjalan di browser peserta, sementara satu-satunya kunci yang kita punya adalah kunci yang bypass RLS.

### Biaya, dan kenapa retensi jadi kewajiban

Audio TTS dari Gemini di proyek ini: 24.000 Hz, 16-bit, mono (lihat `_write_wave_file`, `services.py:166-177`).

```
24.000 sampel/detik x 2 byte = 48.000 byte/detik = 46,9 KB/detik
1 menit audio                = 2,75 MB
```

WAV tidak terkompresi sama sekali. Kalau kuota storage di paket yang kamu pakai 1 GB, itu habis di sekitar 350 audio satu menit — bukan 350 peserta, melainkan 350 kali klik. Angka kuota persisnya **perlu kamu verifikasi sendiri** di halaman pricing Supabase, jangan kutip dari materi ini.

Konsekuensinya jelas: begitu kamu memutuskan menyimpan artifact secara permanen, kamu juga berutang mekanisme retensi. Itu tidak dikerjakan hari ini (lihat bagian 8), dan itu adalah utang teknis yang sadar, bukan yang terlupakan.

### Alternatif yang ditolak

| Pendekatan | Cara kerjanya | Kenapa ditolak |
| --- | --- | --- |
| Tetap lokal, cukup perbaiki cleanup | `try/finally` rapi, kolom `artifact` dibuang saja | `get_last_artifact_by_user_id` tetap mustahil dipakai; setiap permintaan ulang berarti generate TTS lagi — mahal dan lambat |
| Simpan `telegram_file_id` | Telegram jadi CDN gratis, cukup simpan ID-nya | Nol biaya storage, tapi terkunci ke Telegram: file tidak bisa diproses ulang, tidak bisa dipakai dashboard web, dan hilang kalau suatu saat pindah platform |
| Bucket public + URL permanen | Simpan URL publik, tidak perlu signed URL | Rekaman suara dan laporan belajar adalah data pribadi. Ditolak atas dasar privasi, bukan teknis |
| S3 atau Cloudflare R2 | Object storage yang lebih matang | Menambah satu vendor lagi padahal Supabase sudah jadi dependensi. R2 baru menang kalau biaya egress jadi masalah nyata |

Pilihan kita — bucket private, object key di database, file tetap dikirim ke Telegram sebagai file biner — punya satu kelemahan yang tidak boleh disembunyikan: **file efektif dikirim dua kali**, sekali ke Supabase dan sekali ke Telegram. Di jalur `listening_exercise` yang sudah lambat karena dua panggilan Gemini berurutan, ini menambah latensi lagi. Kita menerimanya karena mengirim signed URL ke Telegram membawa masalah yang lebih besar: batas ukuran fetch-by-URL Telegram (perlu diverifikasi di dokumentasi Bot API) dan URL yang bisa kedaluwarsa di tengah jalan.

## 8. Yang Sengaja Tidak Dikerjakan

Ditulis eksplisit supaya tidak dikira lupa:

- **Retensi.** Tidak ada yang menghapus objek lama. Bucket akan tumbuh selamanya. Solusinya cron atau `pg_cron` yang menghapus objek berumur lebih dari N hari, dan itu keputusan produk (berapa lama laporan belajar perlu tersimpan?), bukan keputusan teknis.
- **Kompresi WAV ke OGG/MP3.** Memotong ukuran file sekitar sepuluh kali lipat — dampaknya ke biaya jauh lebih besar daripada pilihan storage mana pun. Tidak dimasukkan karena menambah dependensi `ffmpeg` dan mengaburkan fokus materi.
- **Memindahkan file sementara ke direktori temp OS.** `src/output/` masih di dalam source tree. Untuk deployment sekarang ini aman karena filesystem FastAPI Cloud writable dan file hanya hidup dalam satu request. Tapi kalau suatu hari kamu deploy ke platform dengan filesystem read-only, ini akan gagal total. Jadi bahan Latihan 6.
- **Membersihkan baris lama di kolom `artifact`.** Dibiarkan bercampur, dan jadi bahan Latihan 4.

---

## Latihan

### Latihan 1 (C3) — PDF laporan sampai ke Storage

Jalankan `/report` di Telegram, lalu buktikan tiga hal:

1. PDF-nya sampai di Telegram dengan caption berisi rentang tanggal
2. `src/output/` kembali kosong setelah pengiriman
3. Ada baris baru di `chat_histories` dengan `artifact` berisi object key berawalan `document/`, dan objek itu benar-benar ada di bucket dengan content-type `application/pdf`

Verifikasi poin 3 lewat kode, bukan lewat dashboard:

```bash
uv run python -c "
import src.core.env as env
import src.core.supabase as supabase

client = supabase.get_supabase_client()
baris = (
    client.table('chat_histories')
    .select('artifact')
    .like('artifact', 'document/%')
    .order('created_at', desc=True)
    .limit(1)
    .execute()
).data[0]

key = baris['artifact']
print('object key :', key)
print('info       :', client.storage.from_(env.SUPABASE_BUCKET).info(key))
"
```

### Latihan 2 (C3) — Latihan listening menyusul

Ulangi Latihan 1 untuk audio listening. Object key-nya harus berawalan `audio/`, content-type `audio/wav`.

### Latihan 3 (C4) — Telusuri kebocoran dari snapshot lama

Ambil versi `src/app.py` sebelum perubahan hari ini:

```bash
git show HEAD:src/app.py > /tmp/app-lama.py
```

Tanpa membaca materi bagian 5, temukan minimal **tiga** kebocoran file di file itu. Untuk setiap temuan tulis: nomor baris, skenario konkret yang memicunya, dan akibatnya bagi pengguna.

### Latihan 4 (C4) — Data lama yang tidak kompatibel

Kolom `artifact` sekarang berisi dua jenis nilai: path lokal (baris lama) dan object key (baris baru).

Tulis fungsi yang membedakan keduanya dan mengembalikan `None` untuk baris yang tidak bisa dipakai lagi. Lalu jawab dalam tulisan: apakah baris lama sebaiknya dihapus, dibiarkan, atau ditandai? Pertahankan pilihanmu dengan menyebut siapa yang dirugikan oleh masing-masing pilihan.

### Latihan 5 (C5) — Code review kode yang dikomentari

Ini kode yang benar-benar ada di repo ini sebelum materi hari ini, di `src/agents/services.py:182,199-200`:

```python
    # supabase_client.storage.create_bucket("output")
    ...
    # with open(audio_output_path) as audio_:
    #     supabase_client.storage.from_("output").upload(audio_)
```

Lakukan code review sebagaimana kamu me-review PR rekan kerja. Temukan **minimal empat** cacat. Untuk setiap cacat: apa yang terjadi kalau kode ini di-deploy apa adanya, dan apa perbaikannya.

Petunjuk arah, bukan jawaban: pikirkan apa yang terjadi pada pemanggilan **kedua**; apa yang terjadi pada file **biner**; apakah fungsi `upload()` bisa tahu ke mana file itu harus disimpan; dan apakah `"output"` layak jadi nama bucket di project yang dipakai bersama aplikasi lain.

### Latihan 6 (C6) — Rancang dan bangun `/ulangi`

Buat perintah `/ulangi` yang mengirim ulang artifact terakhir milik peserta, tanpa generate ulang ke Gemini.

Tidak ada satu jawaban benar. Kamu bebas memilih: membuat signed URL lalu mengirim URL-nya, mengunduh objek dari Storage ke file sementara lalu mengirim filenya, atau menyimpan `telegram_file_id` sejak awal dan memakai itu.

Yang wajib ada di jawabanmu:

- perintah `/ulangi` yang jalan di Telegram
- penanganan tiga kondisi: peserta belum pernah punya artifact; nilai `artifact` berupa path lokal lama; objek sudah tidak ada di bucket
- satu paragraf yang menjelaskan trade-off pilihanmu dan alternatif yang kamu tolak

Petunjuk: `get_last_artifact_by_user_id` (`chat_repository.py:59-70`) sudah ada dan belum pernah dipanggil dari mana pun. Sekarang ia baru bisa berguna.

---

## Asesmen

### Kuis (C1/C2) — 5 soal

1. Kenapa file tidak bisa dikembalikan langsung sebagai hasil function calling Gemini?
2. Apa yang terjadi kalau `artifacts.add()` dipanggil tanpa `artifacts.start()` sebelumnya?
3. Kenapa `user_id` tidak bisa ditambahkan sebagai parameter `listening_exercise`?
4. Apa beda yang disimpan di kolom `artifact` sebelum dan sesudah materi ini, dan kenapa yang baru lebih baik?
5. Kenapa `upload_file` mengembalikan `None` saat gagal, bukan melempar exception?

<details>
<summary>Kunci jawaban</summary>

1. Karena hasil pemanggilan tool dikembalikan ke model sebagai teks untuk diolah jadi jawaban. Tidak ada mekanisme mengembalikan biner. Karena itu dibuat jalur samping berbasis `contextvars`.
2. `_artifacts.get()` mengembalikan `None`, dan `add()` langsung `return` tanpa melakukan apa-apa (`artifacts.py:23-25`). File tetap dibuat tapi tidak pernah terkirim, dan tidak ada error sama sekali di log.
3. Karena `listening_exercise` dipanggil berantai dari `skill_type_classification`, yang merupakan tool terdaftar. Signature tool dibaca Gemini sebagai deskripsi parameter, jadi Gemini akan mencoba mengisi `user_id` sendiri dengan nilai karangan.
4. Sebelumnya path lokal absolut yang filenya sudah dihapus beberapa milidetik kemudian. Sesudahnya object key yang menunjuk ke objek nyata di bucket, tidak punya masa berlaku, dan bisa diubah jadi signed URL kapan saja.
5. Karena kegagalan mengarsipkan tidak boleh membatalkan layanan ke peserta. Audio latihan tetap harus sampai walau Supabase sedang bermasalah. Konsekuensinya pemanggil wajib memeriksa nilai kembaliannya.

</details>

### Checklist C3

- [ ] `uv run python -m scripts.init_storage` sukses dijalankan dua kali berturut-turut
- [ ] `import src.core.storage` gagal saat `SUPABASE_BUCKET` dikosongkan, dan sukses saat diisi
- [ ] latihan listening menghasilkan objek berawalan `audio/` dengan content-type `audio/wav`
- [ ] `/report` menghasilkan objek berawalan `document/` dengan content-type `application/pdf`
- [ ] `src/output/` kosong setelah keduanya dijalankan

### Rubrik Latihan 5 (C5, code review)

| Kriteria | Belum (1) | Cukup (2) | Baik (3) |
| --- | --- | --- | --- |
| Jumlah cacat ditemukan | < 2 | 2-3 | >= 4 |
| Kedalaman | menyebut "salah" tanpa alasan | menyebut error yang muncul | menjelaskan kapan error muncul (pemanggilan pertama vs kedua) |
| Perbaikan | tidak ada | ada tapi menambal gejala | menyentuh akar masalah (provisioning keluar dari jalur request) |
| Sikap review | menyalahkan penulis | netral | menunjukkan bagian yang sudah benar juga |

### Rubrik Latihan 6 (C6)

| Kriteria | Belum (1) | Cukup (2) | Baik (3) | Sangat baik (4) |
| --- | --- | --- | --- | --- |
| Kebenaran alur | `/ulangi` tidak jalan | jalan untuk kasus normal | jalan dan tidak generate ulang ke Gemini | jalan, dan artifact yang terkirim identik dengan yang asli |
| Penanganan kasus gagal | tidak ada | satu kasus ditangani | dua kasus | ketiga kasus ditangani dengan pesan yang bisa dimengerti pengguna |
| Keamanan akses | bucket dibuat public agar mudah | tetap private, signed URL berumur panjang | tetap private, umur URL sesuai kebutuhan | plus alasan pemilihan durasinya ditulis |
| Kejelasan trade-off | tidak ada | menyebut pilihan tanpa alasan | menyebut alternatif yang ditolak | menyebut alternatif, alasan, dan kondisi yang akan membuatnya berubah pikiran |

Perhatikan bahwa rubrik ini **tidak menilai pendekatan mana yang dipilih**. Ketiga pendekatan bisa mendapat nilai penuh. Yang dinilai adalah apakah konsekuensi pilihannya dipikirkan.

---

## Verifikasi End-to-End

Kerjakan berurutan. Nomor 3 dan 4 sama wajibnya — kode yang hanya diuji di jalur bahagia belum diuji.

### 1. Statis

```bash
uv run python -c "import src.core.storage; print('OK')"
```

Kosongkan `SUPABASE_BUCKET` di `.env`, jalankan lagi, pastikan gagal dengan `RuntimeError`. Kembalikan nilainya.

### 2. Provisioning

```bash
uv run python -m scripts.init_storage
uv run python -m scripts.init_storage   # harus tetap sukses
```

### 3. Jalur bahagia

```bash
uv run python main.pooling.py
```

Di Telegram: kirim `buatkan latihan listening`, lalu `/report`.

Yang harus benar:

- audio dan PDF sampai di Telegram, keduanya dengan caption
- `ls src/output/` kosong
- dua baris baru di `chat_histories` dengan `artifact` berisi object key (bukan path)
- kedua objek ada di bucket dengan content-type yang benar

### 4. Kasus gagal

| Yang diuji | Cara memicunya | Yang harus terjadi |
| --- | --- | --- |
| Upload gagal | Ubah `SUPABASE_BUCKET` ke nama bucket yang tidak ada, restart bot | Teks dan file **tetap sampai** ke Telegram. Kolom `artifact` tidak terisi. Ada `logger.error` di log |
| File lokal hilang | Hapus manual isi `src/output/` saat bot sedang memproses | Handler tidak crash, ada `logger.warning`, bot tetap membalas |
| Dua artifact sekaligus | Tambahkan sementara satu `artifacts.add()` kedua di `listening_exercise` | Kedua file terkirim, kedua file terhapus |
| PDF menumpuk | Jalankan `/report` sepuluh kali | `src/output/` tetap kosong |
| MIME ditolak | Coba upload `.txt` ke bucket lewat `scripts/coba_storage.py` | Ditolak server karena `allowed_mime_types` |

### 5. Regresi mode webhook

```bash
uv run fastapi dev main.py
curl -s http://127.0.0.1:8000/health-check
```

Pastikan penghapusan `supabase_client` di `main.py:41` tidak memutus apa pun.

---

## Ringkasan Perubahan File

| File | Perubahan |
| --- | --- |
| `src/core/env.py` | tambah `SUPABASE_BUCKET` |
| `.env`, `.env.example` | tambah `SUPABASE_BUCKET` |
| `scripts/init_storage.py` | **baru** — provisioning bucket, idempoten |
| `src/core/storage.py` | **baru** — `build_object_key`, `upload_file`, `create_signed_url`, `remove` |
| `src/core/artifacts.py` | `Artifact` dan `add()` menerima `object_key` |
| `src/agents/services.py` | buang kode Storage mati dan `supabase_client` yang tidak terpakai; `generate_report` mendaftar lewat `artifacts.add()` |
| `src/agents/lead.py` | `_persist_artifacts()`; `handle_report` memanggil `artifacts.start()` dan mengembalikan artifact |
| `src/repository/chat_repository.py` | `save_artifact()` menerima `object_key` dan `kind` |
| `src/app.py` | `_send_artifact` dengan `try/finally`; `handle_text` mengirim semua artifact; `report_command` lewat `_send_artifact`; `handle_voice` dengan `try/finally` |
| `main.py` | buang `supabase_client` yang tidak terpakai |

Catatan: `src/app_cli.py` sengaja tidak disentuh. File itu sisa eksperimen, tidak dipakai entrypoint mana pun, dan memang sudah rusak sejak sebelum materi ini (`app_cli.py:29` memperlakukan `response["artifacts"]` sebagai objek Supabase). Kalau kamu ingin memperbaikinya, itu latihan tambahan yang bagus.
