# Haismart Local — Perangkat Haier di Home Assistant, tanpa cloud

**🌐 [English](../../README.md) · Bahasa Indonesia · [ไทย](README.th.md) · [Tiếng Việt](README.vi.md) · [Bahasa Melayu](README.ms.md) · [Filipino](README.fil.md)**

Kendalikan perangkat Haier Anda dari Home Assistant sepenuhnya melalui jaringan Anda sendiri.
Anda cukup masuk **satu kali** agar integrasi ini dapat mengambil kunci enkripsi unit Anda — setelah
itu Home Assistant hanya berbicara dengan perangkat itu di LAN Anda melalui TCP port 56800. Membaca
status dan mengirim perintah tidak pernah keluar dari jaringan Anda, dan tetap berfungsi meski
internet Anda mati.

> ⚠️ Halaman ini adalah ringkasan. **Dokumentasi lengkap hanya tersedia dalam bahasa Inggris** —
> lihat [README utama](../../README.md) untuk pemasangan lanjutan, pemecahan masalah, contoh
> otomatisasi, dan cara menjadi sepenuhnya bebas cloud.

> ℹ️ Layar integrasi itu sendiri tersedia dalam bahasa Indonesia.

## Apakah perangkat saya didukung?

**Yang menentukan adalah aplikasi yang Anda pakai, bukan negara Anda.** Jika perangkat Anda
dipasangkan dengan aplikasi **Haier / Haismart** (juga bermerek *Haier U+* atau *uHome*), Anda
berada di tempat yang tepat.

| Aplikasi Anda | Didukung di sini? | Gunakan sebagai gantinya |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Ya** | — |
| hOn (sebagian besar Eropa) | ❌ Tidak — modul ini tidak membuka port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (Tiongkok daratan) | ❌ Tidak — cloud berbeda | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (AS / GE Appliances) | ❌ Tidak — platform sepenuhnya berbeda | — |
| SmartAir2 / Smart Clima (unit lama) | ❌ Tidak — port sama, protokol lama tanpa enkripsi | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Pemeriksaan cepat:** jika `nc -z <ip-perangkat-anda> 56800` berhasil, protokol lokalnya aktif.

Perangkat yang **tidak punya modul Wi-Fi sendiri** — lampu, stopkontak, tirai, sensor pintu dan
gerak yang berada di balik gateway Haier — tidak dapat dijangkau dengan aplikasi apa pun: perangkat
itu tidak punya alamat sendiri dan tidak berbicara dengan protokol ini.

### AC

Inilah yang paling matang dan paling banyak diuji. Unit yang sudah dipastikan bekerja ada di
[`DEVICES.md`](../../DEVICES.md). Model Anda tidak tercantum? Kemungkinan besar tetap berfungsi, dan
bukan karena kebetulan: integrasi ini sudah membawa deskripsi resmi **setiap AC dalam katalog
pabrikan — 1.451 kode produk yang mencakup 1.416 nomor model** — setelan apa yang dimiliki tiap
model, nama tiap kerusakan, dan kontrol mana yang diabaikan dalam kondisi tertentu, sehingga ia
menyiapkan dirinya sendiri untuk unit yang belum pernah kami lihat.

> Katalog pabrikan disaring menurut wilayah **dan** menurut kategori produk — itulah yang membuat AC jendela mudah terlewat. Di sini **setiap kategori AC dari setiap wilayah** ikut disertakan.

### Perangkat lainnya

Pemanas air (listrik, gas, dan pompa kalor), kulkas, mesin cuci, mesin pencuci piring, penghisap
asap dapur, kompor gas, lemari sterilisasi, oven, dan pembersih udara juga didukung — **165 tipe
produk dalam 36 kelas perangkat** — tetapi melalui mekanisme yang berbeda: bukan kode khusus per
perangkat, melainkan peta byte resmi Haier untuk tipe produk itu, disaring oleh deklarasi unit Anda
sendiri tentang fitur apa yang benar-benar dimilikinya.

⚠️ Petanya berasal dari pabrikan, **tetapi sebagian besar kategori tersebut belum pernah diuji pada
perangkat nyata di sini**. Sejauh ini hanya **satu** pengaturan pada perangkat selain AC yang pernah
berhasil dikirim — suhu setelan pemanas air pompa kalor, yang diterima oleh perangkat itu dan
dibaca ulang. Selebihnya belum terbukti. Jika Anda memiliki salah satunya, mohon
[laporkan](../TROUBLESHOOTING.md#before-you-open-an-issue) — termasuk bila semuanya berjalan lancar.
Rinciannya ada di [Appliance support in detail](../appliances.md) (bahasa Inggris).

## Apa yang Anda dapatkan

### AC

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
[What you get](../../README.md#what-you-get).

### Perangkat lainnya

Entitasnya dibangun dari peta byte pabrikan ditambah deklarasi unit itu sendiri: angka yang dapat
ditulis menjadi **number** dengan rentang unit Anda sendiri, daftar pilihan menjadi **dropdown**
dengan label pabrikan, saklar menjadi **switch**, pembacaan menjadi **sensor** dengan satuan yang
benar, dan tabel kerusakan menjadi sensor **Fault** milik perangkat itu. Pemanas air juga mendapat
entitas `water_heater` tersendiri, lengkap dengan rentang suhu dan mode kerjanya sendiri.

## Pemasangan

1. Pastikan [HACS](https://hacs.xyz/) sudah terpasang.
1. HACS → menu tiga titik → **Custom repositories** → `https://github.com/enapt/haismart-local`,
   tipe **Integration** → **Add**.
1. Cari **Haismart** → **Download**.
1. **Mulai ulang Home Assistant.** Kode integrasi khusus hanya dimuat saat startup.

Lalu: **Settings → Devices & Services → + Add Integration → Haismart**.

## Penyiapan

Pilih **Masuk** (disarankan): masukkan email (atau nomor telepon) dan kata sandi akun Haier Anda,
beserta negara tempat **akun** Anda didaftarkan. Integrasi akan mendaftar perangkat Anda, mengambil
kuncinya secara otomatis, dan menemukannya di jaringan Anda.

> ⚠️ **Kesalahan penyiapan yang paling sering:** kolom negara adalah **kode telepon negara tempat
> akun Haier Anda dibuat** — bukan tempat perangkat dipasang, dan belum tentu tempat Anda tinggal
> sekarang.
> Jika salah, server Haier melaporkan "akun tidak terdaftar", yang terlihat seperti kata sandi salah.

**Masuk dengan Google atau Facebook?** Akun tersebut tidak punya kata sandi. Buat akun Haier dengan
email dan kata sandi, **bagikan perangkat ke akun itu** di aplikasi, lalu gunakan akun tersebut di
sini.

### Sudah punya kunci lokal unit ini?

Jalur luring, yang hampir tidak menanyakan apa pun. Home Assistant mencari perangkat Haier di
jaringan Anda, meminta masing-masing memperkenalkan diri, lalu menampilkan yang menjawab — Anda
tinggal memilih milik Anda dan menempelkan kuncinya. Alamat dan ID perangkat diambil dari perangkat
itu sendiri.

Setelah itu akan ditanyakan **model apa** yang Anda miliki, berupa daftar pendek model-model dalam
keluarga produk unit Anda, menurut nomor yang tercetak pada labelnya. Menjawabnya berguna: itu
membuka nama-nama kerusakan, aturan ketersediaan, dan daftar fitur asli unit Anda. **Melewatinya
tidak masalah** — aturan yang disepakati semua model dalam keluarga tersebut akan dipakai, dan itu
tetap mencakup seluruh nama kerusakan.

> Kunci adalah satu-satunya hal yang tidak akan diberikan oleh perangkat. Jika Anda tidak
> menyimpannya —
> dari sensor *Local key* pemasangan sebelumnya, atau dari cadangan — gunakan **Masuk** saja; cara
> itu mengambilkannya untuk Anda.

### Kalau perangkat terus meminta kunci baru

Perangkat yang masih terhubung ke server Haier menerima **kunci lokal baru beberapa kali sehari**.
Bila entri ditambahkan tanpa akun Haier, Home Assistant tidak dapat mengambil yang baru — sesudah
kunci berganti, mulai ulang berikutnya membuat perangkat berhenti bekerja dan tampak seperti
kehilangan konfigurasi. Menambahkannya ulang secara manual hanya bertahan sampai pergantian
berikutnya.

Dua cara menyelesaikannya untuk selamanya, keduanya sebaiknya dilakukan selagi semuanya masih
berfungsi:

- **Tambahkan akun Haier Anda** ke unit tersebut: Settings → Devices & Services → Haismart →
  perangkat → Reconfigure → *Add your Haier account*. Pergantian kunci lalu diambil otomatis.
- **Atau blokir akses internet perangkat** di router Anda. Kuncinya berhenti berubah dan yang Anda
  miliki tetap berlaku. Kendali lokal tidak terpengaruh dalam kedua kasus.

## Sebelum memasang

- Home Assistant dan perangkat harus berada di **subnet yang sama**. Tidak ada relai cloud sebagai
  cadangan.
- Perangkat hanya menerima **satu sesi lokal dalam satu waktu** (sekitar 17 detik per sesi).
- Memasang ini **tidak menghentikan perangkat Anda berkomunikasi dengan Haier**, kecuali Anda
  memblokirnya dengan firewall.
- **Reservasi DHCP** untuk perangkat itu rapi, tetapi tidak wajib: jika alamatnya berubah, integrasi
  menemukan unit itu lagi lewat ID perangkatnya dan mengikutinya.

## Butuh bantuan?

Laporkan masalah di [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **dalam bahasa
Inggris jika memungkinkan**. Baca dulu [bagian "Before you open an issue"](../TROUBLESHOOTING.md#before-you-open-an-issue)
di panduan pemecahan masalah.
