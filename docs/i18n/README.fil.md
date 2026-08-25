# Haismart Local — Haier aircon sa Home Assistant, walang cloud

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · [Tiếng Việt](README.vi.md) · [Bahasa Melayu](README.ms.md) · Filipino**

Kontrolin ang inyong Haier aircon mula sa Home Assistant nang buo sa sariling network ninyo.
Mag-sign in kayo nang **isang beses** para makuha ng integration ang encryption key ng unit —
pagkatapos noon, ang Home Assistant ay direktang nakikipag-usap na lamang sa aircon sa inyong LAN sa
pamamagitan ng TCP port 56800. Ang pagbasa ng estado at pagpapadala ng utos ay hindi na lumalabas ng
inyong network, at patuloy itong gumagana kahit mawalan kayo ng internet.

> ⚠️ Buod lamang ang pahinang ito. **Nasa Ingles lamang ang kumpletong dokumentasyon** — tingnan ang
> [pangunahing README](../../README.md) para sa mas malalim na pag-install, troubleshooting, mga
> halimbawa ng automation, at kung paano maging ganap na malaya sa cloud.

## Suportado ba ang aking aircon?

**Ang app na ginagamit ninyo ang mahalaga, hindi ang bansa ninyo.** Kung ang inyong aircon ay
ipinapares sa **Haier / Haismart** app (kilala rin bilang *Haier U+* o *uHome*), nasa tamang lugar
kayo.

| Ang app ninyo | Suportado dito? | Gamitin sa halip |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Oo** | — |
| hOn (karamihan sa Europa) | ❌ Hindi — hindi binubuksan ng mga module na ito ang port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (mainland China) | ❌ Hindi — ibang cloud | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (US / GE Appliances) | ❌ Hindi — ganap na ibang platform | — |
| SmartAir2 / Smart Clima (mas lumang unit) | ❌ Hindi — parehong port, lumang protocol na walang encryption | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Mabilisang pagsusuri:** kung gumana ang `nc -z <ip-ng-aircon-ninyo> 56800`, aktibo ang lokal na
protocol.

Nakalista sa [`DEVICES.md`](../../DEVICES.md) ang mga unit na kumpirmadong gumagana. Wala roon ang
modelo ninyo? Malamang gumana pa rin ito, at hindi ito swerte lamang: dala na ng integration ang
opisyal na paglalarawan ng **lahat ng 1,416 numero ng modelo** sa katalogo ng gumawa — kung anong mga setting mayroon
ang bawat modelo, ano ang tawag sa bawat depekto, at aling mga kontrol ang binabalewala sa aling
kalagayan — kaya kaya nitong i-configure ang sarili para sa unit na hindi pa namin nakikita. Kung
kayang ilarawan din ng inyong account ang unit, pinagsasama ang dalawa sa halip na pumili ng isa.

> Bago ang **v0.38.0** ang bilang na ito ay 171: ang listahan ay para lamang sa isang rehiyon, kaya hindi makilala ang aircon na inilabas sa ibang bansa. Kung hindi nakilala ng lumang bersyon ang unit mo, malamang makilala na ngayon.

## Ano ang makukuha ninyo

Isang device kada aircon: **Climate** (temperatura, mode, bilis ng bentilador, swing, on/off), mga
sensor ng temperatura sa **loob** at **labas**, mga **switch** (Strong, Quiet, Health, Sleep, Display
light), pagpipiliang **Eco**, sensor ng **Model ID**, sensor ng **Cloud connection** (kung kaya pa
ng aircon na abutin ang mga server ng Haier — kapaki-pakinabang kapag hinarangan ninyo ito), at ang
diagnostic sensor na **Local key**.

> Nasa Ingles pa ang mga screen ng integration para sa wikang Filipino. Kung nais ninyong isalin ang
> mga ito, malugod naming tatanggapin ang isang pull request — tingnan ang
> [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Pag-install

1. Tiyaking naka-install ang [HACS](https://hacs.xyz/).
1. HACS → three-dot menu → **Custom repositories** → `https://github.com/enapt/haismart-local`, uri
   na **Integration** → **Add**.
1. Hanapin ang **Haismart** → **Download**.
1. **I-restart ang Home Assistant.** Sa startup lamang nilo-load ang custom integration code.

Pagkatapos: **Settings → Devices & Services → + Add Integration → Haismart**.

## Pag-set up

Piliin ang **Sign in** (inirerekomenda): ilagay ang email (o numero ng telepono) at password ng
inyong Haier account, at ang bansa kung saan **nakarehistro ang account**. Ililista ng integration
ang inyong mga aircon, awtomatikong kukunin ang key ng napili ninyo, at hahanapin ito sa inyong
network.

> ⚠️ **Ang pinakakaraniwang pagkakamali sa pag-set up:** ang field ng bansa ay ang **dialling code
> ng bansa kung saan ginawa ang inyong Haier account** — hindi kung saan naka-install ang aircon, at
> hindi kinakailangang kung saan kayo nakatira ngayon. Kapag mali ito, iniuulat ng server ng Haier na
> "account not registered", na parang maling password ang dating.

**Nag-sign in ba kayo gamit ang Google o Facebook?** Walang password ang mga account na iyon. Gumawa
ng Haier account gamit ang email at password, **i-share ang aircon sa account na iyon** sa app, at
saka gamitin ang account na iyon dito.

### Mayroon na kayo ng lokal na key ng unit na ito?

Ito ang offline na paraan, at halos wala na itong itinatanong. Hahanapin ng Home Assistant ang mga
Haier device sa inyong network, hihilingin sa bawat isa na magpakilala, at ilalista ang mga sumagot —
piliin lamang ninyo ang sa inyo at i-paste ang key. Ang address at device ID ay mula na mismo sa
aircon.

Pagkatapos ay itatanong nito kung **anong modelo** ang mayroon kayo, sa anyo ng maikling listahan ng
mga modelong kabilang sa parehong pamilya ng produkto ng inyong unit, ayon sa numerong nakalimbag sa
label nito. Sulit itong sagutin: binubuksan nito ang mga pangalan ng depekto, ang mga panuntunan sa
availability, at ang tunay na listahan ng tampok ng inyong unit. **Ayos lang laktawan ito** —
gagamitin ang mga panuntunang pinagkakasunduan ng lahat ng modelo sa pamilyang iyon, at saklaw pa rin
nito ang lahat ng pangalan ng depekto.

> Ang key ang tanging bagay na hindi ibibigay ng aircon. Kung wala kayong naka-save — mula sa *Local
> key* sensor ng dating pag-install, o mula sa backup — gamitin na lamang ang **Sign in**; kukunin
> nito ang key para sa inyo.

### Kung paulit-ulit itong humihingi ng bagong key

Ang aircon na nakakaabot pa sa mga server ng Haier ay binibigyan ng **bagong lokal na key nang
ilang beses sa isang araw**. Kung idinagdag ang entry nang walang Haier account, hindi makakakuha ng
bago ang Home Assistant — pagkatapos magpalit ng key, sa susunod na restart ay hihinto sa paggana ang
device at magmumukhang nawala ang configuration nito. Ang muling pagdagdag nang manu-mano ay tatagal
lamang hanggang sa susunod na palit.

Dalawang paraan para tuluyang matapos ito, at mabuting gawin habang gumagana pa ang lahat:

- **Idagdag ang inyong Haier account** sa unit na iyon: Settings → Devices & Services → Haismart →
  ang device → Reconfigure → *Add your Haier account*. Awtomatiko nang kukunin ang bawat palit ng
  key.
- **O harangan ang internet ng aircon** sa inyong router. Titigil na itong magpalit ng key at
  mananatiling wasto ang hawak ninyo. Hindi apektado ang lokal na kontrol sa alinmang paraan.

## Bago mag-install

- Kailangang nasa **iisang subnet** ang Home Assistant at ang aircon. Walang cloud relay na panghalili.
- Tumatanggap ang aircon ng **isang lokal na session lamang sa bawat pagkakataon** (mga 17 segundo
  kada session).
- Ang pag-install nito ay **hindi humihinto sa pakikipag-usap ng aircon ninyo sa Haier**, maliban
  kung haharangan ninyo ito sa firewall.
- Bigyan ang aircon ng **DHCP reservation** upang hindi magbago ang IP address nito.

## Kailangan ng tulong?

Mag-ulat ng isyu sa [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **sa Ingles
kung maaari**. Basahin muna ang [bahaging "Before you open an issue"](../TROUBLESHOOTING.md#before-you-open-an-issue)
sa pangunahing README.
