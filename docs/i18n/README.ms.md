# Haismart â€” Penghawa dingin Haier dalam Home Assistant, tanpa awan

**ðŸŒ [English](../../README.md) Â· [Bahasa Indonesia](README.id.md) Â· [à¹„à¸—à¸¢](README.th.md) Â· [Tiáº¿ng Viá»‡t](README.vi.md) Â· Bahasa Melayu**

Kawal penghawa dingin Haier anda daripada Home Assistant sepenuhnya melalui rangkaian anda sendiri.
Anda log masuk **sekali sahaja** supaya integrasi ini dapat mengambil kunci penyulitan unit anda â€”
selepas itu Home Assistant hanya berhubung dengan penghawa dingin melalui TCP port 56800 dalam LAN
anda. Membaca status dan menghantar arahan tidak pernah keluar daripada rangkaian anda, dan tetap
berfungsi walaupun Internet anda terputus.

> âš ï¸ Halaman ini ialah ringkasan. **Dokumentasi penuh hanya dalam bahasa Inggeris** â€” lihat
> [README utama](../../README.md) untuk pemasangan lanjutan, penyelesaian masalah, contoh automasi,
> dan cara memutuskan hubungan awan sepenuhnya.

## Adakah penghawa dingin saya disokong?

**Yang penting ialah aplikasi yang anda guna, bukan negara anda.** Jika penghawa dingin anda
dipasangkan dengan aplikasi **Haier / Haismart** (juga berjenama *Haier U+* atau *uHome*), anda
berada di tempat yang betul.

| Aplikasi anda | Disokong di sini? | Guna sebagai ganti |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | âœ… **Ya** | â€” |
| hOn (kebanyakan Eropah) | âŒ Tidak â€” modul ini langsung tidak membuka port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier æ™ºå®¶ (China tanah besar) | âŒ Tidak â€” awan berbeza | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (AS / GE Appliances) | âŒ Tidak â€” platform yang berlainan sama sekali | â€” |
| SmartAir2 / Smart Clima (unit lama) | âŒ Tidak â€” port sama, protokol lama tanpa penyulitan | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Semakan pantas:** jika `nc -z <ip-penghawa-dingin> 56800` berjaya, protokol setempat sedang
mendengar.

Unit yang disahkan berfungsi disenaraikan dalam [`DEVICES.md`](../../DEVICES.md). Model anda tiada di
situ? Besar kemungkinan ia tetap berfungsi â€” integrasi ini membina dirinya daripada perihalan model
yang diberikan oleh profil awan penghawa dingin anda sendiri, bukan daripada jadual tetap setiap model.

## Apa yang anda dapat

Satu peranti bagi setiap penghawa dingin: **Climate** (suhu, mod, kelajuan kipas, ayunan, hidup/mati),
penderia **suhu dalaman** dan **luaran**, **suis** (Kuat, Senyap, Kesihatan, Tidur, Lampu paparan),
pilihan **Eco**, penderia **ID Model**, penderia **Sambungan awan** (sama ada penghawa dingin masih
boleh menghubungi pelayan Haier â€” berguna jika anda menyekatnya), dan penderia diagnostik **Kunci
setempat**.

> â„¹ï¸ Home Assistant tidak menyenaraikan bahasa Melayu sebagai bahasa antara muka, jadi integrasi ini
> tiada terjemahan Melayu. Pengguna di Malaysia dan Brunei biasanya menetapkan Home Assistant kepada
> **Bahasa Indonesia** (sangat serupa dan diterjemahkan sepenuhnya di sini) atau **English**.

## Pemasangan

1. Pastikan [HACS](https://hacs.xyz/) sudah dipasang.
1. HACS â†’ menu tiga titik â†’ **Custom repositories** â†’ `https://github.com/cantruchd/haismart`,
   jenis **Integration** â†’ **Add**.
1. Cari **Haismart** â†’ **Download**.
1. **Mulakan semula Home Assistant.** Kod integrasi tersuai hanya dimuatkan semasa permulaan.

Kemudian: **Settings â†’ Devices & Services â†’ + Add Integration â†’ Haismart**.

## Persediaan

Pilih **Log masuk** (disyorkan): masukkan e-mel (atau nombor telefon) dan kata laluan akaun Haier
anda, berserta negara tempat **akaun** anda didaftarkan. Integrasi akan menyenaraikan penghawa dingin
anda, mengambil kuncinya secara automatik, dan mencarinya dalam rangkaian anda.

> âš ï¸ **Kesilapan persediaan paling lazim:** medan negara ialah **kod telefon negara tempat akaun
> Haier anda dicipta** â€” bukan tempat penghawa dingin dipasang, dan tidak semestinya tempat anda
> tinggal sekarang. Jika silap, pelayan Haier melaporkan "akaun tidak berdaftar", yang kelihatan
> seperti kata laluan salah.

**Log masuk dengan Google atau Facebook?** Akaun tersebut tiada kata laluan. Cipta akaun Haier dengan
e-mel dan kata laluan, **kongsi penghawa dingin kepada akaun itu** dalam aplikasi, kemudian guna
akaun tersebut di sini.

## Sebelum memasang

- Home Assistant dan penghawa dingin mesti berada pada **subnet yang sama**. Tiada geganti awan
  sebagai sandaran.
- Penghawa dingin menerima **satu sesi setempat pada satu masa** (kira-kira 17 saat setiap sesi).
- Memasang ini **tidak menghentikan penghawa dingin anda daripada berhubung dengan Haier**, melainkan
  anda menyekatnya dengan tembok api.
- Berikan penghawa dingin **tempahan DHCP** supaya alamat IP-nya tidak berubah.

## Perlukan bantuan?

Laporkan masalah di [GitHub Issues](https://github.com/cantruchd/haismart/issues) â€” **dalam bahasa
Inggeris jika boleh**. Sila baca [bahagian "Before you open an issue"](../../README.md#before-you-open-an-issue)
dalam README utama dahulu.
