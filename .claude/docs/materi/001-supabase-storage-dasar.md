# 001 — Dasar Supabase Storage: Bucket, Object Key, dan Signed URL

## Audiens dan Prasyarat

Materi ini ditulis untuk peserta kelas Belajar Python Agentic AI yang sudah menjalankan bot Mentor Bahasa Inggris Virtual minimal sekali.

Diasumsikan kamu sudah:

- bisa menjalankan `uv sync` dan `uv run python main.pooling.py` sampai bot membalas di Telegram
- punya `.env` yang lengkap dan project Supabase yang jalan (cloud maupun lokal lewat Supabase CLI)
- paham tabel `chat_histories` dan `chat_users` di proyek ini

**Tidak** diasumsikan kamu pernah menyentuh object storage sama sekali. Semua istilah dijelaskan dari nol.

Materi ini sengaja belum menyentuh kode bot. Semua praktik dilakukan di satu file terpisah supaya kalau salah, bot-mu tetap jalan. Integrasi ke `listening_exercise` dan `generate_report` ada di materi berikutnya (`002-upload-artifact-listening-dan-report.md`).

Versi library yang dipakai saat materi ini ditulis (dari `uv.lock`): `supabase` dan `storage3` **2.31.0**, Python **3.13**. API `storage3` masih sering berubah antar minor version — kalau kamu memakai versi lain, cek ulang signature-nya.

## Learning Objectives

Setelah menyelesaikan materi ini, peserta dapat:

1. **Menyebutkan** (C1) komponen Supabase Storage: bucket, object key, content-type, bucket private vs public, dan signed URL.
2. **Menjelaskan** (C2) kenapa filesystem aplikasi tidak bisa diandalkan untuk menyimpan file yang perlu diakses lagi nanti, dan kapan file lokal masih cukup.
3. **Menerapkan** (C3) upload file ke bucket private memakai `supabase-py` 2.31 beserta content-type yang benar.
4. **Menerapkan** (C3) pembuatan signed URL berbatas waktu dan penghapusan objek.

Materi ini berhenti di C3. Analisis, evaluasi, dan perancangan ada di materi 002.

## Outline dan Alokasi Waktu

| Waktu | Bagian |
| --- | --- |
| 8' | Masalah: file yang hilang dan kolom database yang berbohong |
| 7' | Konsep: filesystem ephemeral vs object storage |
| 5' | Menyiapkan bucket |
| 18' | Praktik bertahap: upload v1 sampai v4 |
| 5' | Private vs public, dan signed URL |
| 2' | Kesalahan umum |
| **45'** | **Total** |

---

## 1. Masalah: File yang Hilang dan Kolom Database yang Berbohong

Jangan mulai dari "ayo pakai Supabase Storage". Mulai dari melihat sendiri apa yang rusak.

Bot ini sudah menyimpan referensi file ke database. Jalankan ini dari root proyek:

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()
hasil = (
    client.table('chat_histories')
    .select('id, message_text, artifact, created_at')
    .not_.is_('artifact', 'null')
    .order('created_at', desc=True)
    .limit(3)
    .execute()
)

for baris in hasil.data:
    print(baris['created_at'], '|', baris['artifact'])
"
```

Di mesin yang dipakai menulis materi ini, keluarannya seperti ini:

```
2026-08-13T01:20:44.724639+00:00 | /Users/muhammadagungrizkyana/development/.../src/output/listening-20260813-081941-...wav
2026-08-13T01:19:54.222964+00:00 | /Users/muhammadagungrizkyana/development/.../src/output/listening-20260813-081856-...wav
```

Sekarang cek apakah file-file itu benar-benar ada:

```bash
ls -la src/output/
```

Kosong.

Kolom `artifact` menyimpan alamat file yang **sudah tidak ada**. Penyebabnya bukan bug misterius, melainkan satu baris yang memang sengaja ditulis di `src/app.py:108`:

```python
os.remove(artifact_path)
```

Setelah audio terkirim ke Telegram, file lokalnya dihapus. Itu keputusan yang masuk akal — kalau tidak dihapus, disk akan penuh. Yang tidak masuk akal adalah tetap menyimpan alamatnya ke database seolah-olah masih bisa dipakai.

Akibat nyata dari ini: fungsi `get_last_artifact_by_user_id` di `src/repository/chat_repository.py:59-70` sudah ditulis, tapi tidak pernah dipanggil dari mana pun. Memang tidak bisa dipakai — nilai yang dikembalikannya menunjuk ke file yang tidak ada.

Ada satu masalah lagi yang belum kelihatan di laptopmu. Proyek ini di-deploy ke FastAPI Cloud. Filesystem di sana **writable, tapi stateless dan ephemeral**: kamu boleh menulis file, tetapi begitu container restart, redeploy, atau request berikutnya jatuh ke instance lain, file itu tidak ada lagi. Jadi `src/output/` aman dipakai sebagai meja kerja sementara di dalam satu request, dan tidak boleh dipakai sebagai tempat menyimpan apa pun yang mau dibuka lagi besok.

Dua masalah, satu solusi: file yang perlu bertahan harus pindah ke tempat yang memang dirancang untuk menyimpan file, dan yang disimpan ke database harus alamat di tempat itu, bukan path lokal.

## 2. Konsep: Filesystem Ephemeral vs Object Storage

Bayangkan meja kerja dan lemari arsip. Meja kerja itu cepat dan dekat, tapi setiap malam dibersihkan petugas — apa pun yang tertinggal di sana hilang. Lemari arsip lebih jauh dan butuh waktu untuk membuka lacinya, tapi isinya masih ada minggu depan.

Analogi berhenti di sini. Mulai sekarang kita pakai istilah aslinya.

**Object storage** adalah layanan penyimpanan file yang diakses lewat HTTP, bukan lewat filesystem. Supabase Storage adalah salah satunya (di belakangnya S3). Istilah yang wajib kamu kenali:

| Istilah | Artinya | Contoh di proyek ini |
| --- | --- | --- |
| **Bucket** | Wadah paling atas. Semua objek harus berada di dalam salah satu bucket. Punya pengaturan sendiri: public/private, batas ukuran file, tipe file yang diizinkan | `mentor-artifacts` |
| **Object** | Satu file yang tersimpan | audio latihan listening |
| **Object key** | Alamat objek di dalam bucket. **Ini string biasa, bukan path filesystem** | `audio/100918936/9f3c1a....wav` |
| **Content-type** | Tipe MIME yang dilekatkan ke objek, menentukan bagaimana browser dan Telegram memperlakukannya | `audio/wav`, `application/pdf` |
| **Bucket public** | Siapa pun yang tahu URL-nya bisa mengunduh, tanpa autentikasi | tidak dipakai di sini |
| **Bucket private** | Hanya bisa diakses dengan kredensial, atau lewat signed URL | dipakai di sini |
| **Signed URL** | URL sementara berisi tanda tangan, berlaku sampai batas waktu yang kamu tentukan lalu mati | untuk mengambil ulang artifact |

Satu hal yang paling sering disalahpahami pemula: **object key bukan path filesystem.** Tidak ada direktori di object storage. `audio/100918936/9f3c1a.wav` adalah satu string utuh yang kebetulan mengandung karakter `/`. Dashboard Supabase menampilkannya seperti folder hanya supaya enak dilihat. Konsekuensinya: kamu tidak perlu "membuat folder" dulu sebelum upload, dan menghapus semua objek berawalan `audio/100918936/` berarti menghapus objek satu per satu, bukan menghapus satu direktori.

Kapan file lokal masih cukup? Kalau file itu hanya hidup di dalam satu request — dibuat, dipakai, dibuang. Itu persis yang terjadi pada audio listening sekarang. Jadi memindahkan file ke object storage **bukan** karena yang lama salah total, melainkan karena kita ingin file itu masih bisa diambil lagi setelah request selesai.

## 3. Menyiapkan Bucket

Bucket dibuat sekali saja, di luar kode aplikasi. Untuk sekarang kita buat lewat dashboard supaya kamu melihat opsi-opsinya secara visual. Di materi 002 kita ganti dengan script supaya bisa diulang oleh semua peserta.

Buka dashboard Storage:

- **Supabase cloud**: `https://supabase.com/dashboard` → pilih project → menu **Storage**
- **Supabase lokal (Supabase CLI)**: `http://127.0.0.1:54323` → menu **Storage**

Cek nilai `SUPABASE_URL` di `.env`-mu untuk tahu kamu yang mana:

```bash
uv run python -c "import src.core.env as env; print(env.SUPABASE_URL)"
```

Kalau keluarannya `http://127.0.0.1:54321`, kamu memakai Supabase lokal.

Buat bucket baru:

- **Name**: `mentor-artifacts`
- **Public bucket**: **OFF**. Ini data latihan peserta, jangan dibuat publik.
- Opsi lain biarkan dulu. Kita atur lewat kode di materi 002.

Verifikasi lewat kode, bukan lewat mata:

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()

for bucket in client.storage.list_buckets():
    print(bucket.id, '| public:', bucket.public, '| limit:', bucket.file_size_limit)
"
```

Keluaran yang diharapkan memuat baris:

```
mentor-artifacts | public: False | limit: None
```

Kalau `public: True`, kembali ke dashboard dan matikan togglenya.

## 4. Praktik Bertahap: Upload v1 sampai v4

Buat direktori dan file baru: `scripts/coba_storage.py`. Direktori `scripts/` belum ada di proyek ini, buat saja. Tidak perlu `__init__.py`.

### Cara menjalankannya (baca ini dulu, jangan dilewati)

```bash
uv run python -m scripts.coba_storage
```

Perhatikan `-m` dan titik, bukan garis miring. Kalau kamu menjalankan dengan cara yang lebih intuitif:

```bash
uv run python scripts/coba_storage.py     # GAGAL
```

kamu akan dapat:

```
ModuleNotFoundError: No module named 'src'
```

Alasannya: saat Python menjalankan sebuah file secara langsung, direktori **file itu** yang dimasukkan ke `sys.path`, jadi Python mencari paket `src` di dalam `scripts/`. Dengan `-m`, yang dimasukkan adalah direktori kerja saat ini (root proyek), sehingga `src` ketemu. Proyek ini tidak dipasang sebagai package, jadi tidak ada jalan pintas lain.

Satu catatan lagi: `src/core/env.py` memvalidasi **semua** env var saat di-import dan langsung `raise RuntimeError` kalau ada yang kosong. Kalau `.env`-mu belum lengkap, script ini gagal sebelum menyentuh Storage sama sekali. Itu bukan bug, itu memang perilaku yang diinginkan (fail-fast).

### v1 — upload `bytes` mentah

Tujuan langkah ini cuma satu: memastikan koneksi ke Storage jalan.

```python
# scripts/coba_storage.py
import src.core.supabase as supabase

BUCKET = "mentor-artifacts"

client = supabase.get_supabase_client()

hasil = client.storage.from_(BUCKET).upload(
    path="latihan/hello.txt",
    file=b"halo dari python",
)

print("object key :", hasil.path)
print("full path  :", hasil.full_path)
```

```bash
uv run python -m scripts.coba_storage
```

Keluaran:

```
object key : latihan/hello.txt
full path  : mentor-artifacts/latihan/hello.txt
```

Buka dashboard Storage. Kamu akan melihat "folder" `latihan` berisi `hello.txt` — padahal kamu tidak pernah membuat folder itu. Inilah yang dimaksud object key bukan path.

Perhatikan bedanya `path` dan `full_path`: yang pertama alamat di dalam bucket, yang kedua sudah termasuk nama bucket. Yang nanti kita simpan ke database adalah `path`.

### v2 — upload file nyata, dan kenapa `"rb"` wajib

Sekarang ganti dengan file `.wav` sungguhan. Supaya tidak perlu menjalankan bot dulu, kita buat file WAV senyap memakai modul `wave` bawaan Python — parameternya sengaja disamakan dengan `_write_wave_file` di `src/agents/services.py:166-177`.

```python
# scripts/coba_storage.py
import wave

import src.core.supabase as supabase

from pathlib import Path

BUCKET = "mentor-artifacts"

client = supabase.get_supabase_client()


def buat_wav_dummy(path: Path):
    """Audio senyap 1 detik, 24 kHz mono 16-bit — sama seperti keluaran TTS Gemini."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 24000)


berkas_lokal = Path("src/output/dummy.wav")
berkas_lokal.parent.mkdir(parents=True, exist_ok=True)
buat_wav_dummy(berkas_lokal)

print("ukuran file:", berkas_lokal.stat().st_size, "byte")

with open(berkas_lokal, "rb") as f:  # "rb" = read binary
    hasil = client.storage.from_(BUCKET).upload(path="latihan/dummy.wav", file=f)

print("object key :", hasil.path)
```

Keluaran:

```
ukuran file: 48044 byte
object key : latihan/dummy.wav
```

Angka 48.044 byte itu bukan kebetulan: 24.000 sampel per detik × 2 byte per sampel = 48.000 byte, ditambah 44 byte header WAV. Ingat angka ini, kita pakai lagi untuk menghitung biaya di materi 002.

Sekarang lakukan kesalahan ini dengan sengaja. Hapus `"rb"`:

```python
with open(berkas_lokal) as f:  # tanpa "rb" — SALAH
```

Jalankan lagi:

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0x80 in position 24: invalid start byte
```

Tanpa `"rb"`, Python membuka file dalam mode teks dan mencoba menerjemahkan byte audio sebagai karakter UTF-8. File biner tidak bisa diperlakukan begitu.

Kesalahan ini bukan buatan. Ia persis ada di kode proyek ini, dalam bentuk komentar di `src/agents/services.py:199-200`:

```python
# with open(audio_output_path) as audio_:
#     supabase_client.storage.from_("output").upload(audio_)
```

Kembalikan `"rb"` sebelum lanjut.

> Catatan: `storage3` 2.31 sebenarnya juga menerima `file=berkas_lokal` (objek `Path`) dan membukanya sendiri dengan `"rb"` di dalam. Kita tetap memakai `open(..., "rb")` secara eksplisit karena kamu akan sering menemuinya di kode orang lain dan harus tahu kenapa.

### v3 — content-type

Buka file `latihan/dummy.wav` dari dashboard. Kemungkinan besar ia tidak diputar sebagai audio. Cek tipenya:

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()
info = client.storage.from_('mentor-artifacts').info('latihan/dummy.wav')
print(info)
"
```

Content-type-nya `text/plain;charset=UTF-8`. Ini bukan tebakan salah dari Supabase, ini memang nilai default `storage3` (lihat `DEFAULT_FILE_OPTIONS` di `storage3/constants.py`). Kalau kamu tidak menyebutkan tipenya, semua file kamu akan dianggap teks.

Tambahkan `file_options`:

```python
with open(berkas_lokal, "rb") as f:
    hasil = client.storage.from_(BUCKET).upload(
        path="latihan/dummy.wav",
        file=f,
        file_options={"content-type": "audio/wav"},
    )
```

### v4 — upload key yang sama dua kali

Jalankan script v3 dua kali berturut-turut. Yang kedua gagal:

```
storage3.exceptions.StorageApiError: {'statusCode': 409, 'error': Duplicate, 'message': ...}
```

Status 409 artinya objek dengan key itu sudah ada. Object storage tidak menimpa file secara diam-diam — itu perilaku yang benar, karena menimpa file orang lain karena kebetulan nama key-nya sama adalah bencana.

Kalau memang mau menimpa, minta secara eksplisit:

```python
        file_options={"content-type": "audio/wav", "upsert": "true"},
```

Perhatikan nilainya string `"true"`, bukan boolean `True`. Nilai itu diteruskan sebagai HTTP header `x-upsert`, dan header selalu berupa string.

Tapi di aplikasi nyata, `upsert` biasanya bukan jawaban yang benar. Jawaban yang benar adalah **object key yang tidak mungkin tabrakan sejak awal**. Itu yang kita bangun di materi 002 dengan `uuid`.

Pesan error persisnya bisa sedikit berbeda antar versi Storage API. Yang penting dan stabil adalah status `409`.

## 5. Private vs Public, dan Signed URL

Bucket `mentor-artifacts` kita private. Buktikan.

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()
url = client.storage.from_('mentor-artifacts').get_public_url('latihan/dummy.wav')
print(url)
"
```

`get_public_url()` tetap mengembalikan URL — fungsi ini hanya merangkai string, ia tidak pernah bertanya ke server apakah bucketnya public. Coba akses:

```bash
curl -i "<tempel URL di sini>"
```

Kamu akan dapat respons error, bukan file. Ini penting dipahami: **URL yang terbentuk tidak berarti URL yang bisa diakses.**

Untuk bucket private, cara yang benar adalah signed URL:

```bash
uv run python -c "
import src.core.supabase as supabase

client = supabase.get_supabase_client()
hasil = client.storage.from_('mentor-artifacts').create_signed_url(
    path='latihan/dummy.wav', expires_in=60
)
print(hasil)
print()
print(hasil.get('signedURL') or hasil.get('signedUrl'))
"
```

Dua hal yang harus kamu perhatikan:

1. Kembaliannya **dict**, bukan string. Dan di `storage3` 2.31 dict itu berisi kunci yang sama dengan dua ejaan berbeda: `signedURL` dan `signedUrl`. Pakai `hasil.get("signedURL") or hasil.get("signedUrl")` supaya kodemu tidak pecah kalau salah satunya hilang di versi berikutnya.
2. `expires_in` dalam **detik**. Nilai 60 berarti URL itu mati satu menit lagi.

`curl` URL tersebut sekarang: dapat file. Tunggu lebih dari 60 detik, `curl` lagi: ditolak.

Kalau Supabase-mu lokal, URL-nya berisi `http://127.0.0.1:54321/...` sehingga hanya bisa diakses dari mesin yang sama. Itu wajar dan bukan kesalahan konfigurasi.

Sekarang kamu punya bahan untuk menjawab sendiri: **kenapa signed URL tidak boleh disimpan ke kolom database?** Karena ia punya tanggal kedaluwarsa, sedangkan baris database tidak. Simpan object key — object key tidak pernah kedaluwarsa, dan signed URL bisa dibuat ulang dari object key kapan saja dalam satu baris kode.

## 6. Kesalahan Umum

1. **`uv run python scripts/coba_storage.py`** → `ModuleNotFoundError: No module named 'src'`. Pakai `uv run python -m scripts.coba_storage`.
2. **`open(path)` tanpa `"rb"`** untuk file biner → `UnicodeDecodeError`. Persis bug di `services.py:200`.
3. **Lupa `content-type`** → semua objek jadi `text/plain;charset=UTF-8`.
4. **Memanggil `create_bucket()` di dalam jalur request** → sukses sekali, lalu 409 selamanya. Ini persis yang akan terjadi kalau komentar di `services.py:182` diaktifkan apa adanya.
5. **Object key memakai nama asli file** (`upload.wav`, `laporan.pdf`) → tabrakan antar user, dan nama file kadang membocorkan informasi.
6. **Menyimpan signed URL ke database** → kolom penuh URL mati.
7. **`.env` belum lengkap** → `RuntimeError: env variabel ... belum di-set` sebelum kode Storage-mu sempat jalan.

---

## Latihan

### Latihan 1 (C3) — Upload PDF dengan content-type yang benar

Buat file PDF apa pun (boleh hasil `/report` dari bot, boleh PDF sembarang), upload ke `mentor-artifacts` dengan object key `latihan/laporan.pdf` dan content-type `application/pdf`.

Kriteria selesai:

- `client.storage.from_(...).info('latihan/laporan.pdf')` menunjukkan content-type `application/pdf`
- file bisa dibuka dari dashboard dan terbaca sebagai PDF

### Latihan 2 (C3) — Buktikan signed URL kedaluwarsa

Buat signed URL untuk `latihan/laporan.pdf` dengan `expires_in=30`. Catat hasil `curl -i` pada detik ke-5 dan pada detik ke-40.

Kriteria selesai: kamu bisa menunjukkan dua status HTTP yang berbeda dan menjelaskan bedanya.

### Latihan 3 (C3) — Bersihkan objek latihan

Hapus semua objek berawalan `latihan/` memakai `remove()`, lalu buktikan objeknya benar-benar hilang memakai `exists()`.

Petunjuk: `remove()` menerima **list of string**, bukan satu string. Dan karena tidak ada direktori sungguhan di object storage, kamu harus menyebutkan setiap object key satu per satu — mulai dengan `list()` untuk mendapatkan daftarnya.

### Latihan 4 (C2) — Jelaskan dengan kalimatmu sendiri

Tulis 3-5 kalimat yang menjawab: kenapa kolom `chat_histories.artifact` sebaiknya berisi object key, bukan signed URL, dan bukan path lokal? Sebutkan satu skenario konkret yang rusak untuk masing-masing pilihan yang kamu tolak.

---

## Asesmen

### Kuis (C1/C2) — 5 soal

1. Apa beda bucket dan object key?
2. Apa yang terjadi kalau kamu upload file dengan object key yang sudah ada, tanpa `upsert`?
3. `get_public_url()` pada bucket private mengembalikan apa?
4. Berapa lama signed URL dengan `expires_in=3600` berlaku?
5. Sebutkan satu alasan kenapa `src/output/` tidak boleh dipakai menyimpan file yang mau dibuka besok.

<details>
<summary>Kunci jawaban</summary>

1. Bucket adalah wadah paling atas dengan pengaturannya sendiri (public/private, batas ukuran, tipe file). Object key adalah alamat satu objek **di dalam** bucket, berupa string biasa — bukan path filesystem, dan `/` di dalamnya hanya konvensi tampilan.
2. `StorageApiError` dengan status 409 (Duplicate). Objek lama tidak tertimpa.
3. Tetap mengembalikan string URL yang tersusun rapi, karena fungsi itu hanya merangkai string tanpa bertanya ke server. URL-nya tidak bisa dipakai mengunduh; aksesnya ditolak.
4. 3600 detik = 1 jam sejak URL dibuat.
5. Karena filesystem aplikasi di FastAPI Cloud stateless dan ephemeral: writable, tapi isinya hilang saat container restart/redeploy atau saat request jatuh ke instance lain. Alasan lain yang juga diterima: `src/app.py:108` memang menghapus file itu segera setelah terkirim.

</details>

### Checklist C3 (diverifikasi, bukan diakui sendiri)

Peserta dinyatakan mencapai C3 kalau bisa menunjukkan bukti untuk keempat hal ini:

- [ ] `list_buckets()` menampilkan `mentor-artifacts` dengan `public: False`
- [ ] objek `latihan/dummy.wav` ada dengan content-type `audio/wav` (dibuktikan lewat `info()`, bukan lewat tampilan dashboard)
- [ ] dua keluaran `curl -i` untuk signed URL yang sama dengan status berbeda sebelum dan sesudah kedaluwarsa
- [ ] `exists()` mengembalikan `False` untuk semua objek `latihan/` setelah `remove()`

### Rubrik Latihan 4 (C2)

| Kriteria | Belum | Cukup | Baik |
| --- | --- | --- | --- |
| Alasan menolak path lokal | menyebut "file dihapus" saja | menyebut penghapusan di `app.py:108` | menyebut juga sifat ephemeral filesystem deployment |
| Alasan menolak signed URL | menyebut "kedaluwarsa" saja | menjelaskan bahwa baris DB tidak punya masa berlaku, URL punya | menyebut bahwa object key bisa dipakai membuat URL baru kapan saja |
| Skenario konkret | tidak ada | ada satu | ada untuk kedua pilihan yang ditolak |

---

## Yang Belum Dikerjakan di Materi Ini

Sengaja ditunda ke materi 002, supaya satu materi tidak mengajarkan dua hal sekaligus:

- membuat bucket lewat script yang bisa dijalankan berulang tanpa error
- menyimpan nama bucket di env var
- object key yang dijamin unik dengan `uuid`
- menyambungkan semua ini ke `listening_exercise` dan `generate_report`
- apa yang harus dilakukan kalau upload gagal di tengah request
