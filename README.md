<div align="center">

# 📥 Douyin Download

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20MacOS-blue?style=for-the-badge)]()

**A powerful tool for scraping and downloading videos, images, and livestreams from Douyin (抖音)**

[Demo Video](https://youtu.be/XSQflGR09gA) • [Voice-over Demo](https://youtu.be/hOFfKV3Hjf4)

<img width="800" alt="Douyin Download Demo" src="https://github.com/user-attachments/assets/bf0167c9-0965-4dc6-848d-ae6bb66c7e5f" />

</div>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 📹 **Video Download** | Download all videos/images from a user profile |
| ❤️ **Liked Videos** | Support downloading liked videos (requires cookie) |
| 🎶 **Music & Collection** | Download by music or collection (合集) |
| 🔴 **Livestream** | Support downloading livestreams |

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/datnndd/douyin-download.git
cd douyin-download
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Program

```bash
python douyinCommand.py --config config.yml
```

---

## Ghi livestream với giao diện tiếng Việt

### Bản Windows `.exe`

Giải nén **toàn bộ** `dist/DouyinLive-Windows-x64.zip`, giữ nguyên cấu trúc thư mục, rồi mở `DouyinLive.exe`. Bản này dành cho Windows 10/11 64-bit và đã kèm Python, thư viện và FFmpeg. Không cần cài Python trên máy nhận. Giao diện mở trong trình duyệt; nút **Thoát** dừng các luồng và đóng tiến trình ứng dụng.

Video của bản `.exe` mặc định lưu tại `Videos/DouyinLive` của tài khoản Windows. Cấu hình và nhật ký nằm trong `%LOCALAPPDATA%/DouyinLive`, độc lập với thư mục cài ứng dụng. Cookie chỉ giữ trong phiên chạy. Có thể đổi thư mục lưu trong Cài đặt. Cổng mặc định của bản `.exe` là 8766, bản chạy mã nguồn là 8765; nếu cổng bận, ứng dụng chọn cổng khác.

Build lại trên Windows:

```bat
python -m pip install -r requirements.txt -r requirements-build.txt
python build_windows.py
python verify_windows_bundle.py
```

PyInstaller dùng [cơ chế đường dẫn tài nguyên khi đóng gói](https://pyinstaller.org/en/stable/runtime-information.html). ZIP chỉ chứa chương trình, FFmpeg, tài liệu, giấy phép và mã nguồn; không chứa cookie, cấu hình cá nhân hay video đã tải.

### Chạy từ mã nguồn

Chạy `start_livestream.bat` trên Windows, hoặc:

```bash
python livestream_gui.py
```

Giao diện mở tại `http://127.0.0.1:8765` (nếu cổng bận, ứng dụng chọn cổng khác).

1. Nhập link `https://live.douyin.com/<ID>` hoặc ID phòng. Link chia sẻ Douyin dẫn tới phòng live cũng được hỗ trợ.
2. Nhập số phút cần ghi cho phòng đó. Để trống hoặc nhập `0` để ghi từ lúc bắt đầu đến khi live kết thúc. Ví dụ `1,5` = 90 giây.
3. Nhấn **Thêm luồng**, lặp lại cho các phòng khác. Nhấn **Bắt đầu tất cả** để ghi đồng thời, hoặc **Bắt đầu** ở từng dòng.
4. Dùng **Sửa** để thay link/thời lượng trước khi bắt đầu hoặc sau khi dừng. Dùng **Dừng** / **Dừng tất cả** để kết thúc sớm và giữ video đã ghi.
5. Mở **Cài đặt** để đổi thư mục lưu, nhập đường dẫn FFmpeg hoặc cookie Douyin. Cookie chỉ giữ trong bộ nhớ của phiên hiện tại.

Video mặc định lưu tại `Downloaded/live`, tên có ID phòng, thời gian và số phần. Khi luồng bị ngắt, ứng dụng kiểm tra lại trạng thái live, thử kết nối lại và ghi phần tiếp theo sang file riêng. Không tự gộp các phần; khoảng mất mạng có thể làm mất nội dung. Sau 5 lần thử liên tiếp không thành công, dòng đó hiển thị lỗi và giữ những phần đã ghi. Phòng chưa phát live sẽ báo **Không phát live**; ứng dụng không chờ lịch phát trong tương lai.

Số phút là tổng thời lượng video ghi được; thời gian kết nối lại không tính vào đó. Live kết thúc sớm thì video ngắn hơn thời lượng yêu cầu. Đây là ghi trực tiếp từ thời điểm bắt đầu, không lấy lại phần đã phát trước đó.

Đóng tab trình duyệt vẫn tiếp tục ghi. Giữ tiến trình Python chạy và nhấn **Thoát** trên giao diện hoặc **Ctrl+C** trong cửa sổ chạy Python để dừng ứng dụng, lưu video. File MP4 dùng chế độ phân mảnh để giữ phần đã ghi khi bị gián đoạn, theo [tài liệu FFmpeg](https://ffmpeg.org/ffmpeg-all.html).

Yêu cầu: **Python 3.10+**, `pip install -r requirements.txt`, và **FFmpeg**. Đặt FFmpeg trong PATH, nhập đường dẫn ở Cài đặt, hoặc đặt tại `.tools/ffmpeg/bin/ffmpeg.exe`. Bản Windows có thể tải từ [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), được liên kết trên [trang tải FFmpeg](https://ffmpeg.org/download.html). Trên máy đã được chuẩn bị môi trường `.venv` và FFmpeg cục bộ, file `.bat` tự sử dụng chúng.

Ghi một phòng từ dòng lệnh, ví dụ 30 phút:

```bash
python douyinCommand.py --cmd True --link https://live.douyin.com/123456789 --live-minutes 30 --database False
```

Với YAML, đặt `live_minutes: 0` (hoặc số phút cụ thể). Dòng lệnh xử lý các link lần lượt; dùng giao diện để ghi nhiều phòng đồng thời và đặt thời lượng riêng.

Kiểm tra chức năng:

```bash
python -m pytest tests/test_livestream.py -q
```

---

## 🍪 Cookie Configuration (Optional)

> [!TIP]
> Using a cookie allows you to fetch more detailed information from the API.

### How to Get Your Cookie

1. Open **Douyin Web** in your browser
2. Log in to your account
3. Open **DevTools** (`F12`) → **Network** tab
4. Find the `Cookie` field in the request header
5. Copy the following values and add them to `config.yaml`:

```yaml
msToken: "your_value"
ttwid: "your_value"
odin_tt: "your_value"
passport_csrf_token: "your_value"
sid_guard: "your_value"
```

---

## 🔗 Supported Links

### 🎬 Video / Images
| Type | URL Pattern |
|------|-------------|
| Share Link | `https://v.douyin.com/xxxxx/` |
| Direct Link | `https://www.douyin.com/video/xxxxx` |
| Image Posts | `https://www.douyin.com/note/xxxxx` |

### 👤 User Profile
| Type | URL Pattern |
|------|-------------|
| Profile Page | `https://www.douyin.com/user/xxxxx` |
| Posted Works | Download all posted works |
| Liked Works | Download all liked works (requires permission) |

### 📚 Collection & Music
| Type | URL Pattern |
|------|-------------|
| Collection | `https://www.douyin.com/collection/xxxxx` |
| Music | `https://www.douyin.com/music/xxxxx` |

### 🔴 Livestream
| Type | URL Pattern |
|------|-------------|
| Live Room | `https://live.douyin.com/xxxxx` |

---

## 🙏 Credits

> This project is referenced from [jiji262/douyin-downloader](https://github.com/jiji262/douyin-downloader).  
> Thanks to the original author for sharing the source code.

---

<div align="center">

### ⭐ Star this repo if you find it useful!

**Made with ❤️ for the community**

</div>
