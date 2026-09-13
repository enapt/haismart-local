# Haismart Local — Mga Haier appliance sa Home Assistant, walang cloud

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · [Tiếng Việt](README.vi.md) · [Bahasa Melayu](README.ms.md) · Filipino**

Kontrolin ang inyong Haier appliance mula sa Home Assistant nang buo sa sariling network ninyo.
Mag-sign in kayo nang **isang beses** para makuha ng integration ang encryption key ng unit —
pagkatapos noon, ang Home Assistant ay direktang nakikipag-usap na lamang sa appliance sa inyong LAN
sa pamamagitan ng TCP port 56800. Ang pagbasa ng estado at pagpapadala ng utos ay hindi na lumalabas
ng inyong network, at patuloy itong gumagana kahit mawalan kayo ng internet.

> ⚠️ Buod lamang ang pahinang ito. **Nasa Ingles lamang ang kumpletong dokumentasyon** — tingnan ang
> [pangunahing README](../../README.md) para sa mas malalim na pag-install, troubleshooting, mga
> halimbawa ng automation, at kung paano maging ganap na malaya sa cloud.

> ℹ️ Nasa Ingles pa ang mga screen ng integration para sa wikang Filipino. Kung nais ninyong isalin
> ang mga ito, malugod naming tatanggapin ang isang pull request — tingnan ang
> [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Suportado ba ang aking appliance?

**Ang app na ginagamit ninyo ang mahalaga, hindi ang bansa ninyo.** Kung ang inyong appliance ay
ipinapares sa **Haier / Haismart** app (kilala rin bilang *Haier U+* o *uHome*), nasa tamang lugar
kayo.

| Ang app ninyo | Suportado dito? | Gamitin sa halip |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Oo** | — |
| hOn (karamihan sa Europa) | ❌ Hindi — hindi binubuksan ng mga module na ito ang port 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (mainland China) | ❌ Hindi — ibang cloud | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (US / GE Appliances) | ❌ Hindi — ganap na ibang platform | — |
| SmartAir2 / Smart Clima (mas lumang unit) | ❌ Hindi — parehong port, lumang protocol na walang encryption | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Mabilisang pagsusuri:** kung gumana ang `nc -z <ip-ng-appliance-ninyo> 56800`, aktibo ang lokal na
protocol.

Ang mga bagay na **walang sariling Wi-Fi module** — mga bombilya, saksakan, kurtina, at sensor ng
pinto at galaw na nasa likod ng isang Haier gateway — ay hindi maaabot anuman ang app: wala silang
sariling address at hindi sila nagsasalita ng protocol na ito.

### Mga aircon

Ito ang pinakahinog at pinakamasusing nasubukan. Nakalista sa [`DEVICES.md`](../../DEVICES.md) ang
mga unit na kumpirmadong gumagana. Wala roon ang modelo ninyo? Malamang gumana pa rin ito, at hindi
ito swerte lamang: dala na ng integration ang opisyal na paglalarawan ng **bawat aircon sa katalogo
ng gumawa — 1,451 product code na sumasaklaw sa 1,416 numero ng modelo** — kung anong mga setting
mayroon ang bawat modelo, ano ang tawag sa bawat depekto, at aling mga kontrol ang binabalewala sa
aling kalagayan, kaya kaya nitong i-configure ang sarili para sa unit na hindi pa namin nakikita.

> Ang katalogo ng gumawa ay sinasala ayon sa rehiyon **at** ayon sa kategorya ng produkto — iyan ang dahilan kung bakit madaling maiwan ang mga window aircon. Naririto ang **bawat kategorya ng aircon mula sa bawat rehiyon**.

### Iba pang appliance

Suportado rin ang mga water heater (kuryente, gas at heat pump), refrigerator, washing machine,
dishwasher, range hood, gas stove, sterilising cabinet, oven at air purifier — **165 uri ng produkto
sa 36 na klase ng device** — ngunit sa ibang paraan: walang kodigong nakalaan sa bawat appliance,
kundi ang opisyal na byte map ng Haier para sa uring iyon, sinala ng deklarasyon mismo ng inyong
unit kung alin sa mga iyon ang talagang mayroon ito.

⚠️ Sa gumawa nanggaling ang mga mapa, **ngunit karamihan sa mga kategoryang iyon ay hindi pa
nasusubukan sa tunay na kagamitan dito**, at wala pang kahit isang utos na naipadala sa appliance na
hindi aircon. Kung mayroon kayo ng alinman sa mga ito, mangyaring
[iulat ninyo ito](../TROUBLESHOOTING.md#before-you-open-an-issue) — pati na kung maayos ang lahat.
Nasa [Appliance support in detail](../appliances.md) (Ingles) ang mga detalye.

## Ano ang makukuha ninyo

### Mga aircon

Isang device kada aircon: **Climate** (temperatura, mode, bilis ng bentilador, swing, on/off), mga
sensor ng temperatura sa **loob** at **labas**, mga **switch** (Strong, Quiet, Health, Sleep, Display
light), pagpipiliang **Eco**, pagpipilian ng **posisyon ng vane** kung inilalathala ito ng unit
ninyo, sensor ng **Fault** na pinangangalanan ang sira kasama ang code na ipinapakita ng unit,
**self-clean** (isang button at isang sensor), **power** at **energy** kung iniuulat ito ng unit,
**air quality** kung mayroon itong mga probe, **paalala sa pagpapalit ng filter** kung mayroon nito,
at mga diagnostic: **Model ID**, **Cloud connection** (kung kaya pa ng aircon na abutin ang mga
server ng Haier — kapaki-pakinabang kapag hinarangan ninyo ito), at **Local key**.

Nakadepende sa modelo ninyo kung alin ang lalabas: binabasa ng integration ang sariling modelo ng
unit ninyo at inaalok lamang ang talagang mayroon ito. Buong listahan:
[What you get](../../README.md#what-you-get).

### Iba pang appliance

Binubuo ang kanilang mga entity mula sa byte map ng gumawa kasama ang deklarasyon mismo ng unit: ang
isang numerong maisusulat ay nagiging **number** na nasa saklaw na idineklara ng inyong unit, ang
listahan ng pagpipilian ay nagiging **dropdown** na may mga label ng gumawa, ang isang switch ay
nagiging **switch**, ang isang pagbasa ay nagiging **sensor** na may tamang yunit, at ang talaan ng
depekto ay nagiging **Fault** sensor ng mismong appliance na iyon. May sariling entity na
`water_heater` pa ang mga water heater, kasama ang sarili nitong saklaw ng temperatura at mga mode
ng paggana.

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
ang inyong mga appliance, awtomatikong kukunin ang key ng napili ninyo, at hahanapin ito sa inyong
network.

> ⚠️ **Ang pinakakaraniwang pagkakamali sa pag-set up:** ang field ng bansa ay ang **dialling code
> ng bansa kung saan ginawa ang inyong Haier account** — hindi kung saan naka-install ang
> appliance, at hindi kinakailangang kung saan kayo nakatira ngayon. Kapag mali ito, iniuulat ng
> server ng Haier na "account not registered", na parang maling password ang dating.

**Nag-sign in ba kayo gamit ang Google o Facebook?** Walang password ang mga account na iyon. Gumawa
ng Haier account gamit ang email at password, **i-share ang appliance sa account na iyon** sa app,
at saka gamitin ang account na iyon dito.

### Mayroon na kayo ng lokal na key ng unit na ito?

Ito ang offline na paraan, at halos wala itong itinatanong. Hahanapin ng Home Assistant ang mga
Haier device sa inyong network, hihilingin sa bawat isa na magpakilala, at ilalista ang mga sumagot —
piliin lamang ninyo ang sa inyo at i-paste ang key. Ang address at device ID ay mula na mismo sa
appliance.

Pagkatapos ay itatanong nito kung **anong modelo** ang mayroon kayo, sa anyo ng maikling listahan ng
mga modelong kabilang sa parehong pamilya ng produkto ng inyong unit, ayon sa numerong nakalimbag sa
label nito. Sulit itong sagutin: binubuksan nito ang mga pangalan ng depekto, ang mga panuntunan sa
availability, at ang tunay na listahan ng tampok ng inyong unit. **Ayos lang laktawan ito** —
gagamitin ang mga panuntunang pinagkakasunduan ng lahat ng modelo sa pamilyang iyon, at saklaw pa rin
nito ang lahat ng pangalan ng depekto.

> Ang key ang tanging bagay na hindi ibibigay ng appliance. Kung wala kayong naka-save — mula sa
> *Local key* sensor ng dating pag-install, o mula sa backup — gamitin na lamang ang **Sign in**;
> kukunin nito ang key para sa inyo.

### Kung paulit-ulit itong humihingi ng bagong key

Ang appliance na nakakaabot pa sa mga server ng Haier ay binibigyan ng **bagong lokal na key nang
ilang beses sa isang araw**. Kung idinagdag ang entry nang walang Haier account, hindi makakakuha ng
bago ang Home Assistant — pagkatapos magpalit ng key, sa susunod na restart ay hihinto sa paggana ang
device at magmumukhang nawala ang configuration nito. Ang muling pagdagdag nang manu-mano ay tatagal
lamang hanggang sa susunod na palit.

Dalawang paraan para tuluyang matapos ito, at mabuting gawin habang gumagana pa ang lahat:

- **Idagdag ang inyong Haier account** sa unit na iyon: Settings → Devices & Services → Haismart →
  ang device → Reconfigure → *Add your Haier account*. Awtomatiko nang kukunin ang bawat palit ng
  key.
- **O harangan ang internet ng appliance** sa inyong router. Titigil na itong magpalit ng key at
  mananatiling wasto ang hawak ninyo. Hindi apektado ang lokal na kontrol sa alinmang paraan.

## Bago mag-install

- Kailangang nasa **iisang subnet** ang Home Assistant at ang appliance. Walang cloud relay na
  panghalili.
- Tumatanggap ang appliance ng **isang lokal na session lamang sa bawat pagkakataon** (mga 17
  segundo kada session).
- Ang pag-install nito ay **hindi humihinto sa pakikipag-usap ng appliance ninyo sa Haier**, maliban
  kung haharangan ninyo ito sa firewall.
- Maayos ang **DHCP reservation** para sa appliance ngunit hindi kailangan: kapag nagbago ang IP
  address nito, hahanapin muli ng integration ang unit sa device ID nito at susunod dito.

## Kailangan ng tulong?

Mag-ulat ng isyu sa [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **sa Ingles
kung maaari**. Basahin muna ang [bahaging "Before you open an issue"](../TROUBLESHOOTING.md#before-you-open-an-issue)
sa gabay sa troubleshooting.
