# Haismart Local — Penghawa dingin Haier dalam Home Assistant, tanpa awan

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · [Tiếng Việt](README.vi.md) · Bahasa Melayu · [Filipino](README.fil.md)**

Kawal penghawa dingin Haier anda daripada Home Assistant sepenuhnya melalui rangkaian anda sendiri.
Anda log masuk **sekali sahaja** supaya integrasi ini dapat mengambil kunci penyulitan unit anda —
selepas itu Home Assistant hanya berhubung dengan penghawa dingin melalui TCP port 56800 dalam LAN
anda. Membaca status dan menghantar arahan tidak pernah keluar daripada rangkaian anda, dan tetap
berfungsi walaupun Internet anda terputus.

> ⚠️ Halaman ini ialah ringkasan. **Dokumentasi penuh hanya dalam bahasa Inggeris** — lihat
> [README utama](../../README.md) untuk pemasangan lanjutan, penyelesaian masalah, contoh automasi,
> dan cara memutuskan hubungan awan sepenuhnya.

## Adakah penghawa dingin saya disokong?

**Yang penting ialah aplikasi yang anda guna, bukan negara anda.** Jika penghawa dingin anda
dipasangkan dengan aplikasi **Haier / Haismart** (juga berjenama *Haier U+* atau *uHome*), anda
berada di tempat yang betul.

| Aplikasi anda | Disokong di sini? | Guna sebagai ganti |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Ya** | — |
| hOn (kebanyakan Eropah) | ❌ Tidak — modul ini langsung tidak membuka port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (China tanah besar) | ❌ Tidak — awan berbeza | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (AS / GE Appliances) | ❌ Tidak — platform yang berlainan sama sekali | — |
| SmartAir2 / Smart Clima (unit lama) | ❌ Tidak — port sama, protokol lama tanpa penyulitan | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Semakan pantas:** jika `nc -z <ip-penghawa-dingin> 56800` berjaya, protokol setempat sedang
mendengar.

Unit yang disahkan berfungsi disenaraikan dalam [`DEVICES.md`](../../DEVICES.md). Model anda tiada di
situ? Besar kemungkinan ia tetap berfungsi, dan bukan secara kebetulan: integrasi ini sudah membawa
perihalan rasmi **kesemua 171 penghawa dingin** dalam rangkaian ini — tetapan yang ada pada setiap
model, nama bagi setiap kerosakan, dan kawalan mana yang diabaikan dalam keadaan tertentu — jadi ia
menyediakan dirinya sendiri untuk unit yang belum pernah kami lihat. Jika akaun anda turut boleh
memerihalkan unit itu, kedua-duanya digabungkan, bukan salah satu dipilih.

## Apa yang anda dapat

Satu peranti bagi setiap penghawa dingin: **Climate** (suhu, mod, kelajuan kipas, ayunan, hidup/mati),
penderia **suhu dalaman** dan **luaran**, **suis** (Kuat, Senyap, Kesihatan, Tidur, Lampu paparan),
pilihan **Eco**, penderia **ID Model**, penderia **Sambungan awan** (sama ada penghawa dingin masih
boleh menghubungi pelayan Haier — berguna jika anda menyekatnya), dan penderia diagnostik **Kunci
setempat**.

> ℹ️ Home Assistant tidak menyenaraikan bahasa Melayu sebagai bahasa antara muka, jadi integrasi ini
> tiada terjemahan Melayu. Pengguna di Malaysia dan Brunei biasanya menetapkan Home Assistant kepada
> **Bahasa Indonesia** (sangat serupa dan diterjemahkan sepenuhnya di sini) atau **English**.

## Pemasangan

1. Pastikan [HACS](https://hacs.xyz/) sudah dipasang.
1. HACS → menu tiga titik → **Custom repositories** → `https://github.com/enapt/haismart-local`,
   jenis **Integration** → **Add**.
1. Cari **Haismart** → **Download**.
1. **Mulakan semula Home Assistant.** Kod integrasi tersuai hanya dimuatkan semasa permulaan.

Kemudian: **Settings → Devices & Services → + Add Integration → Haismart**.

## Persediaan

Pilih **Log masuk** (disyorkan): masukkan e-mel (atau nombor telefon) dan kata laluan akaun Haier
anda, berserta negara tempat **akaun** anda didaftarkan. Integrasi akan menyenaraikan penghawa dingin
anda, mengambil kuncinya secara automatik, dan mencarinya dalam rangkaian anda.

> ⚠️ **Kesilapan persediaan paling lazim:** medan negara ialah **kod telefon negara tempat akaun
> Haier anda dicipta** — bukan tempat penghawa dingin dipasang, dan tidak semestinya tempat anda
> tinggal sekarang. Jika silap, pelayan Haier melaporkan "akaun tidak berdaftar", yang kelihatan
> seperti kata laluan salah.

**Log masuk dengan Google atau Facebook?** Akaun tersebut tiada kata laluan. Cipta akaun Haier dengan
e-mel dan kata laluan, **kongsi penghawa dingin kepada akaun itu** dalam aplikasi, kemudian guna
akaun tersebut di sini.

### Sudah ada kunci setempat unit ini?

Laluan luar talian, dan kini ia hampir tidak bertanya apa-apa. Home Assistant mencari peranti Haier
pada rangkaian anda, meminta setiap satu memperkenalkan diri, lalu menyenaraikan yang menjawab —
anda cuma memilih milik anda dan menampal kuncinya. Alamat dan ID peranti datang daripada penghawa
dingin itu sendiri.

Selepas itu ia bertanya **model apa** yang anda miliki, sebagai senarai pendek model dalam keluarga
produk unit anda, mengikut nombor yang tercetak pada labelnya. Menjawabnya berbaloi: ia membuka nama
kerosakan, peraturan ketersediaan, dan senarai ciri sebenar unit anda. **Melangkaunya tidak
mengapa** — peraturan yang dipersetujui oleh semua model dalam keluarga itu akan digunakan, dan itu
tetap merangkumi kesemua nama kerosakan.

> Kunci ialah satu-satunya perkara yang tidak akan diberikan oleh penghawa dingin. Jika anda tiada
> simpanan — daripada penderia *Local key* pemasangan terdahulu, atau daripada sandaran — gunakan
> **Log masuk** sahaja; cara itu mengambilkannya untuk anda.

### Jika ia terus meminta kunci baharu

Penghawa dingin yang masih berhubung dengan pelayan Haier diberi **kunci setempat baharu beberapa
kali sehari**. Jika entri ditambah tanpa akaun Haier, Home Assistant tidak dapat mengambil yang
baharu — selepas kunci bertukar, permulaan semula berikutnya menyebabkan peranti berhenti berfungsi
dan kelihatan seperti kehilangan tetapannya. Menambahnya semula secara manual hanya bertahan sehingga
pertukaran seterusnya.

Dua cara menyelesaikannya buat selamanya, kedua-duanya elok dilakukan sementara semuanya masih
berfungsi:

- **Tambah akaun Haier anda** pada unit itu: Settings → Devices & Services → Haismart → peranti →
  Reconfigure → *Add your Haier account*. Pertukaran kunci kemudian diambil secara automatik.
- **Atau sekat capaian internet penghawa dingin** pada penghala anda. Kuncinya berhenti bertukar dan
  yang anda miliki kekal sah. Kawalan setempat tidak terjejas dalam kedua-dua keadaan.

## Sebelum memasang

- Home Assistant dan penghawa dingin mesti berada pada **subnet yang sama**. Tiada geganti awan
  sebagai sandaran.
- Penghawa dingin menerima **satu sesi setempat pada satu masa** (kira-kira 17 saat setiap sesi).
- Memasang ini **tidak menghentikan penghawa dingin anda daripada berhubung dengan Haier**, melainkan
  anda menyekatnya dengan tembok api.
- Berikan penghawa dingin **tempahan DHCP** supaya alamat IP-nya tidak berubah.

## Perlukan bantuan?

Laporkan masalah di [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **dalam bahasa
Inggeris jika boleh**. Sila baca [bahagian "Before you open an issue"](../../README.md#before-you-open-an-issue)
dalam README utama dahulu.
