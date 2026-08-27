# Haismart Local — AC Haier di Home Assistant, tanpa cloud

**🌐 [English](../../README.md) · Bahasa Indonesia · [ไทย](README.th.md) · [Tiếng Việt](README.vi.md) · [Bahasa Melayu](README.ms.md) · [Filipino](README.fil.md)**

Kendalikan AC Haier Anda dari Home Assistant sepenuhnya melalui jaringan Anda sendiri. Anda cukup
masuk **satu kali** agar integrasi ini dapat mengambil kunci enkripsi unit Anda — setelah itu Home
Assistant hanya berbicara dengan AC di LAN Anda melalui TCP port 56800. Membaca status dan mengirim
perintah tidak pernah keluar dari jaringan Anda, dan tetap berfungsi meski internet Anda mati.

> ⚠️ Halaman ini adalah ringkasan. **Dokumentasi lengkap hanya tersedia dalam bahasa Inggris** —
> lihat [README utama](../../README.md) untuk pemasangan lanjutan, pemecahan masalah, contoh
> otomatisasi, dan cara menjadi sepenuhnya bebas cloud.

## Apakah AC saya didukung?

**Yang menentukan adalah aplikasi yang Anda pakai, bukan negara Anda.** Jika AC Anda dipasangkan
dengan aplikasi **Haier / Haismart** (juga bermerek *Haier U+* atau *uHome*), Anda berada di tempat
yang tepat.

| Aplikasi Anda | Didukung di sini? | Gunakan sebagai gantinya |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Ya** | — |
| hOn (sebagian besar Eropa) | ❌ Tidak — modul ini tidak membuka port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (Tiongkok daratan) | ❌ Tidak — cloud berbeda | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (AS / GE Appliances) | ❌ Tidak — platform sepenuhnya berbeda | — |
| SmartAir2 / Smart Clima (unit lama) | ❌ Tidak — port sama, protokol lama tanpa enkripsi | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Pemeriksaan cepat:** jika `nc -z <ip-ac-anda> 56800` berhasil, protokol lokalnya aktif.

Unit yang sudah dipastikan bekerja ada di [`DEVICES.md`](../../DEVICES.md). Model Anda tidak
tercantum? Kemungkinan besar tetap berfungsi, dan bukan karena kebetulan: integrasi ini sudah
membawa deskripsi resmi **seluruh 1.416 nomor model** dalam katalog pabrikan — setelan apa yang dimiliki tiap
model, nama tiap kerusakan, dan kontrol mana yang diabaikan dalam kondisi tertentu — sehingga ia
menyiapkan dirinya sendiri untuk unit yang belum pernah kami lihat. Jika akun Anda juga bisa
menjelaskan unit tersebut, keduanya digabungkan, bukan dipilih salah satu.

> Katalog pabrikan disaring menurut wilayah **dan** menurut kategori produk — itulah yang membuat AC jendela mudah terlewat. Di sini **setiap kategori AC dari setiap wilayah** ikut disertakan.

## Apa yang Anda dapatkan

Satu perangkat per AC: **Climate** (suhu, mode, kecepatan kipas, swing, nyala/mati), sensor **suhu
dalam** dan **luar ruangan**, **sakelar** (Kuat, Senyap, Kesehatan, Tidur, Lampu layar), pilihan
**Eco**, pilihan **posisi kisi-kisi** bila unit Anda mempublikasikannya, sensor **Kerusakan** yang
menyebutkan nama kerusakan beserta kode yang ditampilkan unit Anda, **pembersihan mandiri** (sebuah
tombol dan sebuah sensor), **daya** dan **energi** bila unit Anda melaporkannya, **kualitas udara**
bila unit Anda punya sensornya, **pengingat ganti filter** bila unit Anda menyimpannya, ditambah
diagnostik: **ID Model**, **Koneksi cloud** (apakah AC masih dapat menghubungi server Haier —
berguna jika Anda memblokirnya), dan **Kunci lokal**.

Yang muncul bergantung pada model Anda: integrasi membaca model unit Anda sendiri dan hanya
menawarkan yang benar-benar dimiliki unit itu. Daftar lengkapnya ada di
[What you get](../../README.md#what-you-get). Antarmuka tersedia dalam bahasa Indonesia.

## Pemasangan

1. Pastikan [HACS](https://hacs.xyz/) sudah terpasang.
1. HACS → menu tiga titik → **Custom repositories** → `https://github.com/enapt/haismart-local`,
   tipe **Integration** → **Add**.
1. Cari **Haismart** → **Download**.
1. **Mulai ulang Home Assistant.** Kode integrasi khusus hanya dimuat saat startup.

Lalu: **Settings → Devices & Services → + Add Integration → Haismart**.

## Penyiapan

Pilih **Masuk** (disarankan): masukkan email (atau nomor telepon) dan kata sandi akun Haier Anda,
beserta negara tempat **akun** Anda didaftarkan. Integrasi akan mendaftar AC Anda, mengambil kuncinya
secara otomatis, dan menemukannya di jaringan Anda.

> ⚠️ **Kesalahan penyiapan yang paling sering:** kolom negara adalah **kode telepon negara tempat
> akun Haier Anda dibuat** — bukan tempat AC dipasang, dan belum tentu tempat Anda tinggal sekarang.
> Jika salah, server Haier melaporkan "akun tidak terdaftar", yang terlihat seperti kata sandi salah.

**Masuk dengan Google atau Facebook?** Akun tersebut tidak punya kata sandi. Buat akun Haier dengan
email dan kata sandi, **bagikan AC ke akun itu** di aplikasi, lalu gunakan akun tersebut di sini.

### Sudah punya kunci lokal unit ini?

Jalur luring, yang hampir tidak menanyakan apa pun. Home Assistant mencari perangkat Haier di
jaringan Anda, meminta masing-masing memperkenalkan diri, lalu menampilkan yang menjawab — Anda
tinggal memilih milik Anda dan menempelkan kuncinya. Alamat dan ID perangkat diambil dari AC itu
sendiri.

Setelah itu akan ditanyakan **model apa** yang Anda miliki, berupa daftar pendek model-model dalam
keluarga produk unit Anda, menurut nomor yang tercetak pada labelnya. Menjawabnya berguna: itu
membuka nama-nama kerusakan, aturan ketersediaan, dan daftar fitur asli unit Anda. **Melewatinya
tidak masalah** — aturan yang disepakati semua model dalam keluarga tersebut akan dipakai, dan itu
tetap mencakup seluruh nama kerusakan.

> Kunci adalah satu-satunya hal yang tidak akan diberikan oleh AC. Jika Anda tidak menyimpannya —
> dari sensor *Local key* pemasangan sebelumnya, atau dari cadangan — gunakan **Masuk** saja; cara
> itu mengambilkannya untuk Anda.

### Kalau AC terus meminta kunci baru

AC yang masih terhubung ke server Haier menerima **kunci lokal baru beberapa kali sehari**. Bila
entri ditambahkan tanpa akun Haier, Home Assistant tidak dapat mengambil yang baru — sesudah kunci
berganti, mulai ulang berikutnya membuat perangkat berhenti bekerja dan tampak seperti kehilangan
konfigurasi. Menambahkannya ulang secara manual hanya bertahan sampai pergantian berikutnya.

Dua cara menyelesaikannya untuk selamanya, keduanya sebaiknya dilakukan selagi semuanya masih
berfungsi:

- **Tambahkan akun Haier Anda** ke unit tersebut: Settings → Devices & Services → Haismart →
  perangkat → Reconfigure → *Add your Haier account*. Pergantian kunci lalu diambil otomatis.
- **Atau blokir akses internet AC** di router Anda. Kuncinya berhenti berubah dan yang Anda miliki
  tetap berlaku. Kendali lokal tidak terpengaruh dalam kedua kasus.

## Sebelum memasang

- Home Assistant dan AC harus berada di **subnet yang sama**. Tidak ada relai cloud sebagai cadangan.
- AC hanya menerima **satu sesi lokal dalam satu waktu** (sekitar 17 detik per sesi).
- Memasang ini **tidak menghentikan AC Anda berkomunikasi dengan Haier**, kecuali Anda memblokirnya
  dengan firewall.
- **Reservasi DHCP** untuk AC itu rapi, tetapi tidak wajib: jika alamatnya berubah, integrasi
  menemukan unit itu lagi lewat ID perangkatnya dan mengikutinya.

## Butuh bantuan?

Laporkan masalah di [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **dalam bahasa
Inggris jika memungkinkan**. Baca dulu [bagian "Before you open an issue"](../TROUBLESHOOTING.md#before-you-open-an-issue)
di panduan pemecahan masalah.
