# Haismart Local — Điều hòa Haier trong Home Assistant, không cần đám mây

**🌐 [English](../../README.md) · [Bahasa Indonesia](README.id.md) · [ไทย](README.th.md) · Tiếng Việt · [Bahasa Melayu](README.ms.md) · [Filipino](README.fil.md)**

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
của **toàn bộ 1.416 số model** trong danh mục của nhà sản xuất — mỗi model có những thiết lập nào, mỗi lỗi
tên là gì, và điều khiển nào bị bỏ qua trong trạng thái nào — nên nó tự cấu hình cho cả máy chưa ai
ở đây từng thấy. Nếu tài khoản của bạn cũng mô tả được máy đó, cả hai nguồn được kết hợp chứ không
chọn một.

> Trước **v0.38.0** con số này là 171: danh sách đó chỉ thuộc một khu vực, nên máy điều hòa công bố ở nước khác không thể nhận dạng được. Nếu bản cũ không nhận ra thiết bị của bạn, bản này rất có thể nhận ra.

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

### Đã có khóa cục bộ của máy này?

Đây là hướng ngoại tuyến, và giờ gần như không hỏi gì cả. Home Assistant tìm các thiết bị Haier
trong mạng của bạn, yêu cầu từng máy tự giới thiệu, rồi liệt kê những máy đã trả lời — bạn chỉ việc
chọn máy của mình và dán khóa vào. Địa chỉ và mã thiết bị đều lấy từ chính chiếc điều hòa.

Sau đó nó hỏi bạn dùng **model nào**, dưới dạng một danh sách ngắn các model cùng dòng sản phẩm với
máy của bạn, theo số in trên nhãn. Trả lời câu này rất đáng: nó mở khóa tên các lỗi, quy tắc khả
dụng và danh sách tính năng thực tế của máy bạn. **Bỏ qua cũng không sao** — hệ thống sẽ dùng những
quy tắc mà mọi model trong dòng đó đều thống nhất, và vẫn bao gồm đầy đủ tên các lỗi.

> Khóa là thứ duy nhất điều hòa sẽ không đưa cho bạn. Nếu bạn không lưu khóa nào — từ cảm biến
> *Local key* của lần cài trước, hoặc từ bản sao lưu — hãy dùng **Đăng nhập**; cách đó sẽ lấy khóa
> giúp bạn.

### Nếu máy cứ đòi khóa mới

Điều hòa còn kết nối được tới máy chủ Haier sẽ được cấp **khóa cục bộ mới vài lần mỗi ngày**. Nếu
thiết bị được thêm mà không có tài khoản Haier, Home Assistant không thể lấy khóa mới — sau khi khóa
đổi, lần khởi động lại kế tiếp sẽ khiến máy ngừng hoạt động và trông như đã mất cấu hình. Thêm lại
thủ công chỉ dùng được đến lần đổi khóa tiếp theo.

Hai cách xử lý dứt điểm, nên làm ngay khi mọi thứ còn chạy tốt:

- **Thêm tài khoản Haier của bạn** vào máy đó: Settings → Devices & Services → Haismart → thiết bị →
  Reconfigure → *Add your Haier account*. Khóa đổi sẽ được lấy tự động.
- **Hoặc chặn điều hòa truy cập internet** trên bộ định tuyến. Khóa sẽ ngừng thay đổi và khóa bạn
  đang có vẫn hợp lệ. Điều khiển cục bộ không bị ảnh hưởng trong cả hai trường hợp.

## Trước khi cài

- Home Assistant và điều hòa phải ở **cùng một subnet**. Không có máy chủ trung chuyển đám mây dự phòng.
- Điều hòa chỉ chấp nhận **một phiên cục bộ tại một thời điểm** (khoảng 17 giây mỗi phiên).
- Cài tích hợp này **không ngăn điều hòa liên lạc với Haier**, trừ khi bạn chặn bằng tường lửa.
- Hãy đặt **DHCP reservation** cho điều hòa để địa chỉ IP không thay đổi.

## Cần trợ giúp?

Báo lỗi tại [GitHub Issues](https://github.com/enapt/haismart-local/issues) — **bằng tiếng Anh nếu
có thể**. Vui lòng đọc [mục "Before you open an issue"](../../README.md#before-you-open-an-issue)
trong README chính trước.
