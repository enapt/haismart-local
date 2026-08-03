# Haismart â€” AC Haier di Home Assistant, tanpa cloud

**ðŸŒ [English](../../README.md) Â· Bahasa Indonesia Â· [à¹„à¸—à¸¢](README.th.md) Â· [Tiáº¿ng Viá»‡t](README.vi.md) Â· [Bahasa Melayu](README.ms.md)**

Kendalikan AC Haier Anda dari Home Assistant sepenuhnya melalui jaringan Anda sendiri. Anda cukup
masuk **satu kali** agar integrasi ini dapat mengambil kunci enkripsi unit Anda â€” setelah itu Home
Assistant hanya berbicara dengan AC di LAN Anda melalui TCP port 56800. Membaca status dan mengirim
perintah tidak pernah keluar dari jaringan Anda, dan tetap berfungsi meski internet Anda mati.

> âš ï¸ Halaman ini adalah ringkasan. **Dokumentasi lengkap hanya tersedia dalam bahasa Inggris** â€”
> lihat [README utama](../../README.md) untuk pemasangan lanjutan, pemecahan masalah, contoh
> otomatisasi, dan cara menjadi sepenuhnya bebas cloud.

## Apakah AC saya didukung?

**Yang menentukan adalah aplikasi yang Anda pakai, bukan negara Anda.** Jika AC Anda dipasangkan
dengan aplikasi **Haier / Haismart** (juga bermerek *Haier U+* atau *uHome*), Anda berada di tempat
yang tepat.

| Aplikasi Anda | Didukung di sini? | Gunakan sebagai gantinya |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | âœ… **Ya** | â€” |
| hOn (sebagian besar Eropa) | âŒ Tidak â€” modul ini tidak membuka port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier æ™ºå®¶ (Tiongkok daratan) | âŒ Tidak â€” cloud berbeda | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (AS / GE Appliances) | âŒ Tidak â€” platform sepenuhnya berbeda | â€” |
| SmartAir2 / Smart Clima (unit lama) | âŒ Tidak â€” port sama, protokol lama tanpa enkripsi | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Pemeriksaan cepat:** jika `nc -z <ip-ac-anda> 56800` berhasil, protokol lokalnya aktif.

Unit yang sudah dipastikan bekerja ada di [`DEVICES.md`](../../DEVICES.md). Model Anda tidak
tercantum? Kemungkinan besar tetap berfungsi â€” integrasi ini menyusun dirinya dari deskripsi model
yang disediakan profil cloud AC Anda sendiri, bukan dari tabel per-model yang ditulis manual.

## Apa yang Anda dapatkan

Satu perangkat per AC: **Climate** (suhu, mode, kecepatan kipas, swing, nyala/mati), sensor **suhu
dalam** dan **luar ruangan**, **sakelar** (Kuat, Senyap, Kesehatan, Tidur, Lampu layar), pilihan
**Eco**, sensor **ID Model**, sensor **Koneksi cloud** (apakah AC masih dapat menghubungi server
Haier â€” berguna jika Anda memblokirnya), serta sensor diagnostik **Kunci lokal**. Antarmuka
tersedia dalam bahasa Indonesia.

## Pemasangan

1. Pastikan [HACS](https://hacs.xyz/) sudah terpasang.
1. HACS â†’ menu tiga titik â†’ **Custom repositories** â†’ `https://github.com/cantruchd/haismart`,
   tipe **Integration** â†’ **Add**.
1. Cari **Haismart** â†’ **Download**.
1. **Mulai ulang Home Assistant.** Kode integrasi khusus hanya dimuat saat startup.

Lalu: **Settings â†’ Devices & Services â†’ + Add Integration â†’ Haismart**.

## Penyiapan

Pilih **Masuk** (disarankan): masukkan email (atau nomor telepon) dan kata sandi akun Haier Anda,
beserta negara tempat **akun** Anda didaftarkan. Integrasi akan mendaftar AC Anda, mengambil kuncinya
secara otomatis, dan menemukannya di jaringan Anda.

> âš ï¸ **Kesalahan penyiapan yang paling sering:** kolom negara adalah **kode telepon negara tempat
> akun Haier Anda dibuat** â€” bukan tempat AC dipasang, dan belum tentu tempat Anda tinggal sekarang.
> Jika salah, server Haier melaporkan "akun tidak terdaftar", yang terlihat seperti kata sandi salah.

**Masuk dengan Google atau Facebook?** Akun tersebut tidak punya kata sandi. Buat akun Haier dengan
email dan kata sandi, **bagikan AC ke akun itu** di aplikasi, lalu gunakan akun tersebut di sini.

## Sebelum memasang

- Home Assistant dan AC harus berada di **subnet yang sama**. Tidak ada relai cloud sebagai cadangan.
- AC hanya menerima **satu sesi lokal dalam satu waktu** (sekitar 17 detik per sesi).
- Memasang ini **tidak menghentikan AC Anda berkomunikasi dengan Haier**, kecuali Anda memblokirnya
  dengan firewall.
- Beri AC **reservasi DHCP** agar alamat IP-nya tidak berubah.

## Butuh bantuan?

Laporkan masalah di [GitHub Issues](https://github.com/cantruchd/haismart/issues) â€” **dalam bahasa
Inggris jika memungkinkan**. Baca dulu [bagian "Before you open an issue"](../../README.md#before-you-open-an-issue)
di README utama.
