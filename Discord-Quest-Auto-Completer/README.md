# Henxi — Discord Quest Auto-Completer Bot

Tool tự động quét, nhận và hoàn thành Discord Quest, đóng gói thành **Discord bot + Web Dashboard**.

---

## Tính năng

| Tính năng | Mô tả |
|---|---|
| **Discord Bot** | Slash commands để quản lý tài khoản, start/stop worker, xem logs |
| **Web Dashboard** | Giao diện web để theo dõi trạng thái, thêm/xóa tài khoản, xem lịch sử |
| **Multi-account** | Chạy nhiều tài khoản cùng lúc, mỗi tài khoản 1 worker thread |
| **Auto Accept** | Tự động đăng ký quest mới |
| **Auto Complete** | Tự động hoàn thành quest bằng heartbeat/video-progress |
| **Rate Limit Handling** | Tự động chờ và retry khi bị 429 |

---

## Cài đặt

### 1. Cài dependencies

```bash
pip install -r requirements.txt
```

### 2. Tạo Discord Bot

1. Vào [Discord Developer Portal](https://discord.com/developers/applications)
2. Tạo Application mới → **Bot**
3. Bật **Message Content Intent** trong Bot Settings
4. Copy **Bot Token**

### 3. Cài đặt biến môi trường

Tạo file `.env` trong thư mục project:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
DASHBOARD_USER=admin
DASHBOARD_PASS=your_secure_password
SESSION_SECRET=any_random_secret_key
```

Hoặc export trực tiếp:

```bash
export DISCORD_BOT_TOKEN=your_token_here
export DASHBOARD_PASS=your_secure_password
```

### 4. Invite bot vào server

1. Trong Developer Portal → OAuth2 → URL Generator
2. Tick scopes: `bot`, `applications.commands`
3. Tick permissions: `Send Messages`, `Use Slash Commands`
4. Dùng link để invite bot vào server

---

## Chạy

### Chạy cả bot + dashboard (mặc định)

```bash
python main.py
```

- Dashboard: `http://localhost:8000`
- Bot prefix: `/` (slash commands)

### Chỉ chạy bot

```bash
python main.py --bot-only
```

### Chỉ chạy dashboard

```bash
python main.py --dashboard-only --port 8080
```

---

## Slash Commands

| Command | Mô tả |
|---|---|
| `/add <token>` | Thêm tài khoản Discord |
| `/list` | Xem danh sách tài khoản |
| `/remove <user_id>` | Xóa tài khoản |
| `/start <user_id> [poll_interval] [auto_accept]` | Bắt đầu auto quest |
| `/stop <user_id>` | Dừng auto quest |
| `/status` | Xem trạng thái worker |
| `/logs [limit]` | Xem lịch sử hoạt động |
| `/stats` | Xem thống kê hệ thống |

---

## Web Dashboard

Đăng nhập tại `http://localhost:8000` với `DASHBOARD_USER` / `DASHBOARD_PASS`.

### Trang Dashboard
- Tổng quan stats: tài khoản, worker đang chạy, quest hoàn thành
- Thêm tài khoản nhanh bằng token
- Danh sách tài khoản với nút Start/Stop
- Hoạt động gần đây

### Trang Tài khoản
- Xem tất cả tài khoản đã thêm
- Start/Stop/Xóa từng tài khoản

### Trang Lịch sử
- Toàn bộ log quest: enrolled, completed, failed

### Trang Cài đặt
- Hướng dẫn biến môi trường
- Danh sách slash commands

---

## Kiến trúc

```
main.py
├── database.py      # SQLite — lưu accounts, tokens, sessions, logs
├── worker.py        # Thread worker — chạy auto-complete cho 1 account
├── bot.py           # Discord bot — slash commands
└── dashboard.py     # FastAPI web server — HTML dashboard
    ├── templates/   # Jinja2 HTML templates
    └── static/      # CSS + JS
```

- **Worker**: mỗi tài khoản chạy trong 1 thread riêng, gửi heartbeat/video-progress theo chu kỳ
- **Dashboard**: chạy trên thread riêng, giao tiếp với worker qua biến shared state
- **Database**: SQLite file `bot_data.db`, dùng WAL mode cho concurrency

---

## Lấy Discord Token

1. Mở Discord (ứng dụng desktop hoặc web)
2. Nhấn `Ctrl+Shift+I` → tab **Network**
3. Đăng nhập lại Discord
4. Tìm request đến `/api/v9/users/@me`
5. Trong headers của request, copy giá trị `Authorization`
6. **Khuyến nghị**: Dùng **Alt Account / Nitro account** để tránh risk main account

> **Cảnh báo**: Sử dụng token Discord tự động có thể vi phạm ToS của Discord. Tool này chỉ dành cho mục đích học tập/nghiên cứu.
