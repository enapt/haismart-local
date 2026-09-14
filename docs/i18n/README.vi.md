# Haismart Local — Thiết bị Haier trong Home Assistant, không cần đám mây

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · Tiếng Việt · [Bahasa Melayu](README.ms.md) · [Filipino](README.fil.md)**

Điều khiển thiết bị Haier của bạn từ Home Assistant hoàn toàn qua mạng nội bộ. Bạn chỉ đăng nhập
**một lần** để tích hợp lấy được khóa mã hóa của máy — sau đó Home Assistant chỉ giao tiếp với chính
thiết bị đó qua TCP cổng 56800 trong mạng LAN của bạn. Việc đọc trạng thái và gửi lệnh không bao giờ
ra khỏi mạng của bạn, và vẫn hoạt động ngay cả khi mất Internet.

> ⚠️ Trang này chỉ là bản tóm tắt. **Tài liệu đầy đủ chỉ có bằng tiếng Anh** — xem
> [README chính](../../README.md) để biết cách cài đặt nâng cao, xử lý sự cố, ví dụ tự động hóa và
> cách tách hoàn toàn khỏi đám mây.

> ℹ️ Bản thân giao diện của tích hợp đã có tiếng Việt.

## Thiết bị của tôi có được hỗ trợ không?

**Điều quan trọng là ứng dụng bạn dùng, không phải quốc gia bạn ở.** Nếu thiết bị của bạn ghép nối
với ứng dụng **Haier / Haismart** (còn có tên *Haier U+* hoặc *uHome*), bạn đã đến đúng chỗ.

| Ứng dụng của bạn | Được hỗ trợ ở đây? | Dùng thay thế |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Có** | — |
| hOn (chủ yếu ở châu Âu) | ❌ Không — các mô-đun này không mở cổng 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (Trung Quốc đại lục) | ❌ Không — đám mây khác | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (Mỹ / GE Appliances) | ❌ Không — nền tảng hoàn toàn khác | — |
| SmartAir2 / Smart Clima (máy đời cũ) | ❌ Không — cùng cổng, giao thức cũ không mã hóa | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Kiểm tra nhanh:** nếu `nc -z <ip-thiết-bị> 56800` thành công thì giao thức nội bộ đang lắng nghe.

Những thứ **không có mô-đun Wi-Fi riêng** — bóng đèn, ổ cắm, rèm, cảm biến cửa và cảm biến chuyển
động nằm sau một gateway Haier — thì không với tới được dù dùng ứng dụng nào: chúng không có địa chỉ
riêng và không nói giao thức này.

### Điều hòa

Đây là trường hợp hoàn thiện nhất và được thử nghiệm nhiều nhất. Các máy đã xác nhận hoạt động được
liệt kê trong [`DEVICES.md`](../../DEVICES.md). Không thấy model của bạn? Rất có thể nó vẫn chạy
được, và không phải nhờ may mắn: tích hợp mang sẵn mô tả chính thức của **mọi điều hòa trong danh
mục của nhà sản xuất — 1.451 mã sản phẩm, bao trùm 1.416 số model** — mỗi model có những thiết lập
nào, mỗi lỗi tên là gì, và điều khiển nào bị bỏ qua trong trạng thái nào, nên nó tự cấu hình cho cả
máy chưa ai ở đây từng thấy.

> Danh mục của nhà sản xuất được lọc theo **khu vực** và theo **danh mục sản phẩm** — đó là lý do máy điều hòa cửa sổ dễ bị bỏ sót. Ở đây có **mọi danh mục điều hòa từ mọi khu vực**.

### Các thiết bị khác

Máy nước nóng (điện, gas và bơm nhiệt), tủ lạnh, máy giặt, máy rửa bát, máy hút mùi, bếp gas, tủ
tiệt trùng, lò nướng và máy lọc không khí cũng được hỗ trợ — **165 loại sản phẩm thuộc 36 lớp thiết
bị** — nhưng bằng một cơ chế khác: không có mã riêng cho từng thiết bị, mà dùng bản đồ byte chính
thức của Haier cho loại sản phẩm đó, lọc qua phần khai báo của chính máy bạn về những tính năng nó
thực sự có.

⚠️ Bản đồ đó là của nhà sản xuất, **nhưng phần lớn các danh mục chưa từng được thử trên máy thật ở
đây**. Cho đến nay chỉ **một** thiết lập trên thiết bị không phải điều hòa từng được gửi thành công
— nhiệt độ cài đặt của một máy nước nóng bơm nhiệt, được thiết bị chấp nhận và đọc lại để xác nhận.
Phần còn lại vẫn chưa được kiểm chứng. Nếu bạn có một trong số đó, xin hãy
[báo lại](../TROUBLESHOOTING.md#before-you-open-an-issue) — kể cả khi mọi thứ chạy tốt.
Chi tiết: [Appliance support in detail](../appliances.md) (tiếng Anh).

## Bạn nhận được gì

### Điều hòa

Mỗi điều hòa là một thiết bị: **Climate** (nhiệt độ đặt, chế độ, tốc độ quạt, đảo gió, bật/tắt), cảm
biến **nhiệt độ trong nhà** và **ngoài trời**, các **công tắc** (Mạnh, Yên tĩnh, Sức khỏe, Ngủ, Đèn
hiển thị), lựa chọn **Eco**, lựa chọn **vị trí cánh gió** nếu máy của bạn công bố chúng, cảm biến
**Lỗi** nêu tên lỗi kèm mã mà máy bạn hiển thị, **tự làm sạch** (một nút bấm và một cảm biến),
**công suất** và **điện năng** nếu máy bạn báo cáo, **chất lượng không khí** nếu máy có cảm biến,
**nhắc thay lưới lọc** nếu máy có, cùng các mục chẩn đoán: **Mã model**, **Kết nối đám mây** (điều
hòa còn liên lạc được với máy chủ Haier hay không — hữu ích nếu bạn chặn nó), và **Khóa cục bộ**.

Những mục xuất hiện tùy theo model của bạn: tích hợp đọc chính model của máy bạn và chỉ cung cấp
những gì máy đó thực sự có. Danh sách đầy đủ: [What you get](../../README.md#what-you-get).

### Các thiết bị khác

Thực thể của chúng được dựng từ bản đồ byte của nhà sản xuất cộng với phần khai báo của chính máy:
một số ghi được thành **number** theo đúng dải giá trị máy bạn khai, một danh sách lựa chọn thành
**dropdown** với nhãn của nhà sản xuất, một công tắc thành **switch**, một giá trị đọc thành
**sensor** với đúng đơn vị, và bảng lỗi thành cảm biến **Fault** của riêng thiết bị đó. Máy nước
nóng còn có thêm thực thể `water_heater` riêng, với dải nhiệt độ và các chế độ vận hành của chính
nó.

## Cài đặt

1. Bảo đảm đã cài [HACS](https://hacs.xyz/).
1. HACS → menu ba chấm → **Custom repositories** → `https://github.com/enapt/haismart-local`,
   loại **Integration** → **Add**.
1. Tìm **Haismart** → **Download**.
1. **Khởi động lại Home Assistant.** Mã của tích hợp tùy chỉnh chỉ được nạp lúc khởi động.

Sau đó: **Settings → Devices & Services → + Add Integration → Haismart**.

## Thiết lập

Chọn **Đăng nhập** (khuyến nghị): nhập email (hoặc số điện thoại) và mật khẩu tài khoản Haier của
bạn, cùng quốc gia nơi **tài khoản** được đăng ký. Tích hợp sẽ liệt kê các thiết bị của bạn, tự động
lấy khóa và tìm thấy máy trong mạng.

> ⚠️ **Lỗi thiết lập phổ biến nhất:** trường quốc gia là **mã điện thoại của quốc gia nơi tài khoản
> Haier được tạo** — không phải nơi lắp thiết bị, và không nhất thiết là nơi bạn đang sống. Nếu chọn
> sai, máy chủ Haier báo "tài khoản chưa đăng ký", nghe như thể sai mật khẩu.

**Đăng nhập bằng Google hoặc Facebook?** Những tài khoản đó không có mật khẩu. Hãy tạo một tài khoản
Haier bằng email và mật khẩu, **chia sẻ thiết bị sang tài khoản đó** trong ứng dụng, rồi dùng tài
khoản ấy ở đây.

### Đã có khóa cục bộ của máy này?

Đây là hướng ngoại tuyến, gần như không hỏi gì cả. Home Assistant tìm các thiết bị Haier
trong mạng của bạn, yêu cầu từng máy tự giới thiệu, rồi liệt kê những máy đã trả lời — bạn chỉ việc
chọn máy của mình và dán khóa vào. Địa chỉ và mã thiết bị đều lấy từ chính chiếc máy đó.

Sau đó nó hỏi bạn dùng **model nào**, dưới dạng một danh sách ngắn các model cùng dòng sản phẩm với
máy của bạn, theo số in trên nhãn. Trả lời câu này rất đáng: nó mở khóa tên các lỗi, quy tắc khả
dụng và danh sách tính năng thực tế của máy bạn. **Bỏ qua cũng không sao** — hệ thống sẽ dùng những
quy tắc mà mọi model trong dòng đó đều thống nhất, và vẫn bao gồm đầy đủ tên các lỗi.

> Khóa là thứ duy nhất thiết bị sẽ không đưa cho bạn. Nếu bạn không lưu khóa nào — từ cảm biến
> *Local key* của lần cài trước, hoặc từ bản sao lưu — hãy dùng **Đăng nhập**; cách đó sẽ lấy khóa
> giúp bạn.

### Nếu máy cứ đòi khóa mới

Thiết bị còn kết nối được tới máy chủ Haier sẽ được cấp **khóa cục bộ mới vài lần mỗi ngày**. Nếu
thiết bị được thêm mà không có tài khoản Haier, Home Assistant không thể lấy khóa mới — sau khi khóa
đổi, lần khởi động lại kế tiếp sẽ khiến máy ngừng hoạt động và trông như đã mất cấu hình. Thêm lại
thủ công chỉ dùng được đến lần đổi khóa tiếp theo.

Hai cách xử lý dứt điểm, nên làm ngay khi mọi thứ còn chạy tốt:

- **Thêm tài khoản Haier của bạn** vào máy đó: Settings → Devices & Services → Haismart → thiết bị →
  Reconfigure → *Add your Haier account*. Khóa đổi sẽ được lấy tự động.
- **Hoặc chặn thiết bị truy cập internet** trên bộ định tuyến. Khóa sẽ ngừng thay đổi và khóa bạn
  đang có vẫn hợp lệ. Điều khiển cục bộ không bị ảnh hưởng trong cả hai trường hợp.

## Trước khi cài

- Home Assistant và thiết bị phải ở **cùng một subnet**. Không có máy chủ trung chuyển đám mây dự
  phòng.
- Thiết bị chỉ chấp nhận **một phiên cục bộ tại một thời điểm** (khoảng 17 giây mỗi phiên).
- Cài tích hợp này **không ngăn thiết bị liên lạc với Haier**, trừ khi bạn chặn bằng tường lửa.
- **DHCP reservation** cho thiết bị thì gọn gàng nhưng không bắt buộc: nếu địa chỉ IP thay đổi,
  tích hợp sẽ tìm lại máy theo ID thiết bị và tự đi theo.

## Cần trợ giúp?

Báo lỗi tại [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **bằng tiếng Anh nếu
có thể**. Vui lòng đọc [mục "Before you open an issue"](../TROUBLESHOOTING.md#before-you-open-an-issue)
trong hướng dẫn khắc phục sự cố trước.
