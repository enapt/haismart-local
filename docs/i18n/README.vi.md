# Haismart Local — Điều hòa Haier trong Home Assistant, không cần đám mây

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · Tiếng Việt · [Bahasa Melayu](README.ms.md)**

Điều khiển điều hòa Haier của bạn từ Home Assistant hoàn toàn qua mạng nội bộ. Bạn chỉ đăng nhập
**một lần** để tích hợp lấy được khóa mã hóa của máy — sau đó Home Assistant chỉ giao tiếp với điều
hòa qua TCP cổng 56800 trong mạng LAN của bạn. Việc đọc trạng thái và gửi lệnh không bao giờ ra khỏi
mạng của bạn, và vẫn hoạt động ngay cả khi mất Internet.

> ⚠️ Trang này chỉ là bản tóm tắt. **Tài liệu đầy đủ chỉ có bằng tiếng Anh** — xem
> [README chính](../../README.md) để biết cách cài đặt nâng cao, xử lý sự cố, ví dụ tự động hóa và
> cách tách hoàn toàn khỏi đám mây.

## Điều hòa của tôi có được hỗ trợ không?

**Điều quan trọng là ứng dụng bạn dùng, không phải quốc gia bạn ở.** Nếu điều hòa của bạn ghép nối
với ứng dụng **Haier / Haismart** (còn có tên *Haier U+* hoặc *uHome*), bạn đã đến đúng chỗ.

| Ứng dụng của bạn | Được hỗ trợ ở đây? | Dùng thay thế |
|---|---|---|
| **Haier / Haismart / Haier U+ / uHome** | ✅ **Có** | — |
| hOn (chủ yếu ở châu Âu) | ❌ Không — các mô-đun này không mở cổng 56800 | [Andre0512/hon](https://github.com/Andre0512/hon) |
| Haier 智家 (Trung Quốc đại lục) | ❌ Không — đám mây khác | [banto6/haier](https://github.com/banto6/haier) |
| SmartHQ (Mỹ / GE Appliances) | ❌ Không — nền tảng hoàn toàn khác | — |
| SmartAir2 / Smart Clima (máy đời cũ) | ❌ Không — cùng cổng, giao thức cũ không mã hóa | [oxystin/homebridge-haier-air-conditioner](https://github.com/oxystin/homebridge-haier-air-conditioner) |

**Kiểm tra nhanh:** nếu `nc -z <ip-điều-hòa> 56800` thành công thì giao thức nội bộ đang lắng nghe.

Các máy đã xác nhận hoạt động được liệt kê trong [`DEVICES.md`](../../DEVICES.md). Không thấy model
của bạn? Rất có thể nó vẫn chạy được, và không phải nhờ may mắn: tích hợp mang sẵn mô tả chính thức
của **toàn bộ 171 máy điều hòa** trong dòng sản phẩm này — mỗi model có những thiết lập nào, mỗi lỗi
tên là gì, và điều khiển nào bị bỏ qua trong trạng thái nào — nên nó tự cấu hình cho cả máy chưa ai
ở đây từng thấy. Nếu tài khoản của bạn cũng mô tả được máy đó, cả hai nguồn được kết hợp chứ không
chọn một.

## Bạn nhận được gì

Mỗi điều hòa là một thiết bị: **Climate** (nhiệt độ đặt, chế độ, tốc độ quạt, đảo gió, bật/tắt), cảm
biến **nhiệt độ trong nhà** và **ngoài trời**, các **công tắc** (Mạnh, Yên tĩnh, Sức khỏe, Ngủ, Đèn
hiển thị), lựa chọn **Eco**, cảm biến **Mã model**, cảm biến **Kết nối đám mây** (điều hòa còn liên
lạc được với máy chủ Haier hay không — hữu ích nếu bạn chặn nó), và cảm biến chẩn đoán **Khóa cục
bộ**. Giao diện có sẵn tiếng Việt.

## Cài đặt

1. Bảo đảm đã cài [HACS](https://hacs.xyz/).
1. HACS → menu ba chấm → **Custom repositories** → `https://github.com/enapt/haismart-local`,
   loại **Integration** → **Add**.
1. Tìm **Haismart** → **Download**.
1. **Khởi động lại Home Assistant.** Mã của tích hợp tùy chỉnh chỉ được nạp lúc khởi động.

Sau đó: **Settings → Devices & Services → + Add Integration → Haismart**.

## Thiết lập

Chọn **Đăng nhập** (khuyến nghị): nhập email (hoặc số điện thoại) và mật khẩu tài khoản Haier của
bạn, cùng quốc gia nơi **tài khoản** được đăng ký. Tích hợp sẽ liệt kê các điều hòa của bạn, tự động
lấy khóa và tìm thấy máy trong mạng.

> ⚠️ **Lỗi thiết lập phổ biến nhất:** trường quốc gia là **mã điện thoại của quốc gia nơi tài khoản
> Haier được tạo** — không phải nơi lắp điều hòa, và không nhất thiết là nơi bạn đang sống. Nếu chọn
> sai, máy chủ Haier báo "tài khoản chưa đăng ký", nghe như thể sai mật khẩu.

**Đăng nhập bằng Google hoặc Facebook?** Những tài khoản đó không có mật khẩu. Hãy tạo một tài khoản
Haier bằng email và mật khẩu, **chia sẻ điều hòa sang tài khoản đó** trong ứng dụng, rồi dùng tài
khoản ấy ở đây.

## Trước khi cài

- Home Assistant và điều hòa phải ở **cùng một subnet**. Không có máy chủ trung chuyển đám mây dự phòng.
- Điều hòa chỉ chấp nhận **một phiên cục bộ tại một thời điểm** (khoảng 17 giây mỗi phiên).
- Cài tích hợp này **không ngăn điều hòa liên lạc với Haier**, trừ khi bạn chặn bằng tường lửa.
- Hãy đặt **DHCP reservation** cho điều hòa để địa chỉ IP không thay đổi.

## Cần trợ giúp?

Báo lỗi tại [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **bằng tiếng Anh nếu
có thể**. Vui lòng đọc [mục "Before you open an issue"](../../README.md#before-you-open-an-issue)
trong README chính trước.
