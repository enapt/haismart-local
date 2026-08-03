# Haismart â€” Äiá»u hÃ²a Haier trong Home Assistant, khÃ´ng cáº§n Ä‘Ã¡m mÃ¢y

**ðŸŒ [English](../../README.md) Â· [Bahasa Indonesia](README.id.md) Â· [à¹„à¸—à¸¢](README.th.md) Â· Tiáº¿ng Viá»‡t Â· [Bahasa Melayu](README.ms.md)**

Äiá»u khiá»ƒn Ä‘iá»u hÃ²a Haier cá»§a báº¡n tá»« Home Assistant hoÃ n toÃ n qua máº¡ng ná»™i bá»™. Báº¡n chá»‰ Ä‘Äƒng nháº­p
**má»™t láº§n** Ä‘á»ƒ tÃ­ch há»£p láº¥y Ä‘Æ°á»£c khÃ³a mÃ£ hÃ³a cá»§a mÃ¡y â€” sau Ä‘Ã³ Home Assistant chá»‰ giao tiáº¿p vá»›i Ä‘iá»u
hÃ²a qua TCP cá»•ng 56800 trong máº¡ng LAN cá»§a báº¡n. Viá»‡c Ä‘á»c tráº¡ng thÃ¡i vÃ  gá»­i lá»‡nh khÃ´ng bao giá» ra khá»i
máº¡ng cá»§a báº¡n, vÃ  váº«n hoáº¡t Ä‘á»™ng ngay cáº£ khi máº¥t Internet.

> âš ï¸ Trang nÃ y chá»‰ lÃ  báº£n tÃ³m táº¯t. **TÃ i liá»‡u Ä‘áº§y Ä‘á»§ chá»‰ cÃ³ báº±ng tiáº¿ng Anh** â€” xem
> [README chÃ­nh](../../README.md) Ä‘á»ƒ biáº¿t cÃ¡ch cÃ i Ä‘áº·t nÃ¢ng cao, xá»­ lÃ½ sá»± cá»‘, vÃ­ dá»¥ tá»± Ä‘á»™ng hÃ³a vÃ 
> cÃ¡ch tÃ¡ch hoÃ n toÃ n khá»i Ä‘Ã¡m mÃ¢y.

## Äiá»u hÃ²a cá»§a tÃ´i cÃ³ Ä‘Æ°á»£c há»— trá»£ khÃ´ng?

**Äiá»u quan trá»ng lÃ  á»©ng dá»¥ng báº¡n dÃ¹ng, khÃ´ng pháº£i quá»‘c gia báº¡n á»Ÿ.** Náº¿u Ä‘iá»u hÃ²a cá»§a báº¡n ghÃ©p ná»‘i
vá»›i á»©ng dá»¥ng **Haier / Haismart** (cÃ²n cÃ³ tÃªn *Haier U+* hoáº·c *uHome*), báº¡n Ä‘Ã£ Ä‘áº¿n Ä‘Ãºng chá»—.

| á»¨ng dá»¥ng cá»§a báº¡n | ÄÆ°á»£c há»— trá»£ á»Ÿ Ä‘Ã¢y? | DÃ¹ng thay tháº¿ |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | âœ… **CÃ³** | â€” |
| hOn (chá»§ yáº¿u á»Ÿ chÃ¢u Ã‚u) | âŒ KhÃ´ng â€” cÃ¡c mÃ´-Ä‘un nÃ y khÃ´ng má»Ÿ cá»•ng 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier æ™ºå®¶ (Trung Quá»‘c Ä‘áº¡i lá»¥c) | âŒ KhÃ´ng â€” Ä‘Ã¡m mÃ¢y khÃ¡c | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (Má»¹ / GE Appliances) | âŒ KhÃ´ng â€” ná»n táº£ng hoÃ n toÃ n khÃ¡c | â€” |
| SmartAir2 / Smart Clima (mÃ¡y Ä‘á»i cÅ©) | âŒ KhÃ´ng â€” cÃ¹ng cá»•ng, giao thá»©c cÅ© khÃ´ng mÃ£ hÃ³a | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Kiá»ƒm tra nhanh:** náº¿u `nc -z <ip-Ä‘iá»u-hÃ²a> 56800` thÃ nh cÃ´ng thÃ¬ giao thá»©c ná»™i bá»™ Ä‘ang láº¯ng nghe.

CÃ¡c mÃ¡y Ä‘Ã£ xÃ¡c nháº­n hoáº¡t Ä‘á»™ng Ä‘Æ°á»£c liá»‡t kÃª trong [`DEVICES.md`](../../DEVICES.md). KhÃ´ng tháº¥y model
cá»§a báº¡n? Ráº¥t cÃ³ thá»ƒ nÃ³ váº«n cháº¡y Ä‘Æ°á»£c â€” tÃ­ch há»£p tá»± dá»±ng nÃªn tá»« mÃ´ táº£ model do chÃ­nh há»“ sÆ¡ Ä‘Ã¡m mÃ¢y cá»§a
Ä‘iá»u hÃ²a cung cáº¥p, chá»© khÃ´ng dá»±a vÃ o báº£ng viáº¿t cá»©ng cho tá»«ng model.

## Báº¡n nháº­n Ä‘Æ°á»£c gÃ¬

Má»—i Ä‘iá»u hÃ²a lÃ  má»™t thiáº¿t bá»‹: **Climate** (nhiá»‡t Ä‘á»™ Ä‘áº·t, cháº¿ Ä‘á»™, tá»‘c Ä‘á»™ quáº¡t, Ä‘áº£o giÃ³, báº­t/táº¯t), cáº£m
biáº¿n **nhiá»‡t Ä‘á»™ trong nhÃ ** vÃ  **ngoÃ i trá»i**, cÃ¡c **cÃ´ng táº¯c** (Máº¡nh, YÃªn tÄ©nh, Sá»©c khá»e, Ngá»§, ÄÃ¨n
hiá»ƒn thá»‹), lá»±a chá»n **Eco**, cáº£m biáº¿n **MÃ£ model**, cáº£m biáº¿n **Káº¿t ná»‘i Ä‘Ã¡m mÃ¢y** (Ä‘iá»u hÃ²a cÃ²n liÃªn
láº¡c Ä‘Æ°á»£c vá»›i mÃ¡y chá»§ Haier hay khÃ´ng â€” há»¯u Ã­ch náº¿u báº¡n cháº·n nÃ³), vÃ  cáº£m biáº¿n cháº©n Ä‘oÃ¡n **KhÃ³a cá»¥c
bá»™**. Giao diá»‡n cÃ³ sáºµn tiáº¿ng Viá»‡t.

## CÃ i Ä‘áº·t

1. Báº£o Ä‘áº£m Ä‘Ã£ cÃ i [HACS](https://hacs.xyz/).
1. HACS â†’ menu ba cháº¥m â†’ **Custom repositories** â†’ `https://github.com/cantruchd/haismart`,
   loáº¡i **Integration** â†’ **Add**.
1. TÃ¬m **Haismart** â†’ **Download**.
1. **Khá»Ÿi Ä‘á»™ng láº¡i Home Assistant.** MÃ£ cá»§a tÃ­ch há»£p tÃ¹y chá»‰nh chá»‰ Ä‘Æ°á»£c náº¡p lÃºc khá»Ÿi Ä‘á»™ng.

Sau Ä‘Ã³: **Settings â†’ Devices & Services â†’ + Add Integration â†’ Haismart**.

## Thiáº¿t láº­p

Chá»n **ÄÄƒng nháº­p** (khuyáº¿n nghá»‹): nháº­p email (hoáº·c sá»‘ Ä‘iá»‡n thoáº¡i) vÃ  máº­t kháº©u tÃ i khoáº£n Haier cá»§a
báº¡n, cÃ¹ng quá»‘c gia nÆ¡i **tÃ i khoáº£n** Ä‘Æ°á»£c Ä‘Äƒng kÃ½. TÃ­ch há»£p sáº½ liá»‡t kÃª cÃ¡c Ä‘iá»u hÃ²a cá»§a báº¡n, tá»± Ä‘á»™ng
láº¥y khÃ³a vÃ  tÃ¬m tháº¥y mÃ¡y trong máº¡ng.

> âš ï¸ **Lá»—i thiáº¿t láº­p phá»• biáº¿n nháº¥t:** trÆ°á»ng quá»‘c gia lÃ  **mÃ£ Ä‘iá»‡n thoáº¡i cá»§a quá»‘c gia nÆ¡i tÃ i khoáº£n
> Haier Ä‘Æ°á»£c táº¡o** â€” khÃ´ng pháº£i nÆ¡i láº¯p Ä‘iá»u hÃ²a, vÃ  khÃ´ng nháº¥t thiáº¿t lÃ  nÆ¡i báº¡n Ä‘ang sá»‘ng. Náº¿u chá»n
> sai, mÃ¡y chá»§ Haier bÃ¡o "tÃ i khoáº£n chÆ°a Ä‘Äƒng kÃ½", nghe nhÆ° thá»ƒ sai máº­t kháº©u.

**ÄÄƒng nháº­p báº±ng Google hoáº·c Facebook?** Nhá»¯ng tÃ i khoáº£n Ä‘Ã³ khÃ´ng cÃ³ máº­t kháº©u. HÃ£y táº¡o má»™t tÃ i khoáº£n
Haier báº±ng email vÃ  máº­t kháº©u, **chia sáº» Ä‘iá»u hÃ²a sang tÃ i khoáº£n Ä‘Ã³** trong á»©ng dá»¥ng, rá»“i dÃ¹ng tÃ i
khoáº£n áº¥y á»Ÿ Ä‘Ã¢y.

## TrÆ°á»›c khi cÃ i

- Home Assistant vÃ  Ä‘iá»u hÃ²a pháº£i á»Ÿ **cÃ¹ng má»™t subnet**. KhÃ´ng cÃ³ mÃ¡y chá»§ trung chuyá»ƒn Ä‘Ã¡m mÃ¢y dá»± phÃ²ng.
- Äiá»u hÃ²a chá»‰ cháº¥p nháº­n **má»™t phiÃªn cá»¥c bá»™ táº¡i má»™t thá»i Ä‘iá»ƒm** (khoáº£ng 17 giÃ¢y má»—i phiÃªn).
- CÃ i tÃ­ch há»£p nÃ y **khÃ´ng ngÄƒn Ä‘iá»u hÃ²a liÃªn láº¡c vá»›i Haier**, trá»« khi báº¡n cháº·n báº±ng tÆ°á»ng lá»­a.
- HÃ£y Ä‘áº·t **DHCP reservation** cho Ä‘iá»u hÃ²a Ä‘á»ƒ Ä‘á»‹a chá»‰ IP khÃ´ng thay Ä‘á»•i.

## Cáº§n trá»£ giÃºp?

BÃ¡o lá»—i táº¡i [GitHub Issues](https://github.com/cantruchd/haismart/issues) â€” **báº±ng tiáº¿ng Anh náº¿u
cÃ³ thá»ƒ**. Vui lÃ²ng Ä‘á»c [má»¥c "Before you open an issue"](../../README.md#before-you-open-an-issue)
trong README chÃ­nh trÆ°á»›c.
