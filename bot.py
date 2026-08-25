"""
ONI QUEST - Discord Auto-Completer (Complete with Web Panel)
Kết hợp Discord Bot + Flask Web Server
"""

import os
import sys
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
import database
from worker import start_worker, stop_worker, get_worker, get_all_workers, get_running_accounts

# ── Flask Web Server ─────────────────────────────────────────────────────────
from flask import Flask, jsonify, request, render_template_string
from threading import Thread

app = Flask(__name__)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("oni_quest")

# ── Bot Setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Lưu tạm mapping: token -> thông tin người dùng Discord
token_to_user = {}

# ── HTML UI Template ─────────────────────────────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Oni Quest Auto-Completer</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: #0a0a0a;
            color: #DCDDDE;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            background: #1e1e1e;
            border-radius: 12px;
            overflow: hidden;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        }

        .header {
            background: #2C2F33;
            border-bottom: 1px solid #202225;
            padding: 16px;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
        }

        .header-content h1 {
            font-size: 16px;
            font-weight: 600;
            color: white;
            margin: 0 0 8px 0;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .header-content p {
            font-size: 13px;
            color: #949BA4;
            line-height: 1.4;
            margin: 0;
        }

        .header-icon {
            width: 24px;
            height: 24px;
            background: #5865F2;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }

        .header-badge {
            width: 64px;
            height: 64px;
            background: #202225;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
            flex-shrink: 0;
        }

        .banner {
            width: 100%;
            height: 200px;
            background: linear-gradient(135deg, #4A148C 0%, #6A1B9A 50%, #7B1FA2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }

        .banner img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }

        .content {
            padding: 16px;
        }

        .features {
            margin-bottom: 16px;
        }

        .feature {
            display: flex;
            gap: 8px;
            margin-bottom: 10px;
            font-size: 13px;
            color: #DCDDDE;
        }

        .feature-icon {
            min-width: 16px;
            font-size: 16px;
        }

        .feature-title {
            color: white;
            font-weight: 500;
        }

        .divider {
            border-top: 1px solid #202225;
            margin: 12px 0;
        }

        .description {
            font-size: 12px;
            color: #72767D;
            line-height: 1.5;
            font-style: italic;
            margin-bottom: 12px;
        }

        .credit {
            font-size: 12px;
            color: #72767D;
            font-style: italic;
            margin-bottom: 16px;
        }

        .buttons {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
        }

        button {
            border: none;
            border-radius: 6px;
            padding: 12px 8px;
            font-weight: 600;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 4px;
            color: white;
        }

        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        button:active {
            transform: translateY(0);
        }

        .btn-auto-quest {
            background: #5865F2;
        }

        .btn-auto-quest:hover {
            background: #4752c4;
        }

        .btn-stats {
            background: #9370DB;
        }

        .btn-stats:hover {
            background: #7d5eb5;
        }

        .btn-stop {
            background: #ED4245;
        }

        .btn-stop:hover {
            background: #d63839;
        }

        button span:first-child {
            font-size: 18px;
        }

        .footer {
            background: #2C2F33;
            text-align: center;
            padding: 12px;
            font-size: 11px;
            color: #72767D;
            border-top: 1px solid #202225;
        }

        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal.show {
            display: flex;
        }

        .modal-content {
            background: #2C2F33;
            border-radius: 8px;
            padding: 20px;
            max-width: 400px;
            width: 90%;
            border: 1px solid #202225;
        }

        .modal-content h2 {
            color: white;
            margin-bottom: 16px;
            font-size: 16px;
        }

        .modal-content input {
            width: 100%;
            padding: 10px;
            background: #202225;
            border: 1px solid #404249;
            border-radius: 6px;
            color: white;
            margin-bottom: 12px;
            font-size: 13px;
        }

        .modal-content input::placeholder {
            color: #72767D;
        }

        .modal-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }

        .modal-buttons button {
            padding: 10px;
            font-size: 13px;
        }

        .btn-submit {
            background: #5865F2;
        }

        .btn-cancel {
            background: #404249;
        }

        .alert {
            display: none;
            position: fixed;
            top: 20px;
            right: 20px;
            background: #202225;
            border: 1px solid #404249;
            border-radius: 6px;
            padding: 16px;
            max-width: 300px;
            z-index: 2000;
            animation: slideIn 0.3s ease-out;
        }

        .alert.show {
            display: block;
        }

        .alert.success {
            border-left: 4px solid #57F287;
        }

        .alert.error {
            border-left: 4px solid #ED4245;
        }

        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>
                    <span class="header-icon">✨</span>
                    QUEST AUTO-COMPLETER
                </h1>
                <p>Chào mừng đến với Quest Auto-Completer!<br/>Nhấn nút bên dưới để quản lý quest của bạn.</p>
            </div>
            <div class="header-badge">💎</div>
        </div>

        <div class="banner" id="banner">
            <img id="banner-img" src="https://media.giphy.com/media/WJmwuUXuLvaSJo9owu/giphy.gif" alt="Discord Orbs" onerror="handleImageError()">
        </div>

        <div class="content">
            <div class="features">
                <div class="feature">
                    <span class="feature-icon">🔑</span>
                    <span><span class="feature-title">Auto Quest</span> — Bắt đầu hoàn thành quest tự động</span>
                </div>

                <div class="feature">
                    <span class="feature-icon">💎</span>
                    <span><span class="feature-title">Thống kê Quest</span> — Xem Quest đã làm, chưa làm, Orbs đã nhận và chưa nhận</span>
                </div>

                <div class="feature">
                    <span class="feature-icon">⏹</span>
                    <span><span class="feature-title">Stop Quest</span> — Dừng phiên hiện tại</span>
                </div>
            </div>

            <div class="divider"></div>

            <div class="description">
                Token chỉ dùng để hoàn thành quest, không lưu trữ.
            </div>

            <div class="credit">
                By: Oni • Quest Auto-Completer
            </div>

            <div class="buttons">
                <button class="btn-auto-quest" onclick="openTokenModal()">
                    <span>🔑</span>
                    <span>Auto Quest</span>
                </button>
                <button class="btn-stats" onclick="handleStats()">
                    <span>💎</span>
                    <span>Thống kê</span>
                </button>
                <button class="btn-stop" onclick="handleStop()">
                    <span>⏹</span>
                    <span>Stop Quest</span>
                </button>
            </div>
        </div>

        <div class="footer">
            ⚡ ONI QUEST SYSTEM • High Performance Auto-Completer
        </div>
    </div>

    <!-- Token Input Modal -->
    <div class="modal" id="tokenModal">
        <div class="modal-content">
            <h2>🔑 Nhập Token Discord</h2>
            <input type="password" id="tokenInput" placeholder="Dán token Discord của bạn tại đây">
            <div class="modal-buttons">
                <button class="btn-submit" onclick="submitToken()">Nhập</button>
                <button class="btn-cancel" onclick="closeTokenModal()">Hủy</button>
            </div>
        </div>
    </div>

    <!-- Alert Message -->
    <div class="alert" id="alert"></div>

    <script>
        // ─────────────────────────────────────────────────────────────────
        // MODAL FUNCTIONS
        // ─────────────────────────────────────────────────────────────────
        function openTokenModal() {
            document.getElementById("tokenModal").classList.add("show");
        }

        function closeTokenModal() {
            document.getElementById("tokenModal").classList.remove("show");
            document.getElementById("tokenInput").value = "";
        }

        async function submitToken() {
            const token = document.getElementById("tokenInput").value.trim();
            if (!token) {
                showAlert("Vui lòng nhập token!", "error");
                return;
            }

            try {
                const response = await fetch("/api/auto-quest", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ token })
                });
                
                const data = await response.json();
                if (data.success) {
                    showAlert(data.message, "success");
                    closeTokenModal();
                } else {
                    showAlert(data.message, "error");
                }
            } catch (error) {
                showAlert("Lỗi: " + error.message, "error");
            }
        }

        // ─────────────────────────────────────────────────────────────────
        // BUTTON HANDLERS
        // ─────────────────────────────────────────────────────────────────
        async function handleStats() {
            try {
                const response = await fetch("/api/stats");
                const data = await response.json();
                
                if (data.success) {
                    showAlert("💎 " + data.message, "success");
                    // Hiển thị stats chi tiết
                    console.log("Stats:", data.stats);
                } else {
                    showAlert(data.message, "error");
                }
            } catch (error) {
                showAlert("Lỗi: " + error.message, "error");
            }
        }

        async function handleStop() {
            if (!confirm("Bạn chắc chắn muốn dừng quest không?")) return;

            try {
                const response = await fetch("/api/stop-quest", { method: "POST" });
                const data = await response.json();
                
                if (data.success) {
                    showAlert("⏹ " + data.message, "success");
                } else {
                    showAlert(data.message, "error");
                }
            } catch (error) {
                showAlert("Lỗi: " + error.message, "error");
            }
        }

        // ─────────────────────────────────────────────────────────────────
        // ALERT SYSTEM
        // ─────────────────────────────────────────────────────────────────
        function showAlert(message, type = "success") {
            const alert = document.getElementById("alert");
            alert.textContent = message;
            alert.className = `alert show ${type}`;
            
            setTimeout(() => {
                alert.classList.remove("show");
            }, 3000);
        }

        // ─────────────────────────────────────────────────────────────────
        // IMAGE ERROR HANDLER
        // ─────────────────────────────────────────────────────────────────
        function handleImageError() {
            document.getElementById("banner").innerHTML = 
                '<div style="width:100%; height:100%; background: linear-gradient(135deg, #4A148C 0%, #6A1B9A 50%, #7B1FA2 100%); display: flex; align-items: center; justify-content: center; color: white; text-align: center; padding: 20px;">' +
                '<div><div style="font-size: 24px; margin-bottom: 10px;">🎨</div>' +
                '<div style="font-size: 13px;">INTRODUCING DISCORD ORBS</div></div>' +
                '</div>';
        }

        // Close modal when clicking outside
        document.getElementById("tokenModal").addEventListener("click", function(e) {
            if (e.target === this) closeTokenModal();
        });

        console.log("Oni Quest Panel loaded!");
    </script>
</body>
</html>
"""

# ── Flask Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve HTML UI"""
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/auto-quest", methods=["POST"])
def api_auto_quest():
    """Handle Auto Quest (Nhập Token + Bắt đầu)"""
    try:
        data = request.json
        token = data.get("token", "").strip()
        
        if not token or len(token) < 50:
            return jsonify({"success": False, "message": "❌ Token không hợp lệ!"})
        
        # Thêm account vào database
        database.add_account(token)
        accounts = database.get_all_accounts()
        account = next((a for a in accounts if a.get("token") == token), None)
        
        if not account:
            return jsonify({"success": False, "message": "❌ Không thể thêm account!"})
        
        user_id = account["user_id"]
        username = account.get("username") or account.get("global_name") or user_id[:12]
        
        # Bắt đầu worker
        if not get_worker(user_id):
            start_worker(token, user_id, username, 60, True)
            return jsonify({
                "success": True, 
                "message": f"🛡️ Thêm và khởi chạy thành công!\n👤 Tài khoản: {username}\n⚡ Trạng thái: 🟢 Đang chạy"
            })
        else:
            return jsonify({
                "success": False,
                "message": f"⚠️ Tài khoản {username} đã chạy rồi!"
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Lỗi: {str(e)}"})

@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Handle Stats"""
    try:
        stats = database.get_stats()
        running_accounts = get_running_accounts()
        all_logs = stats.get("recent_logs", [])
        
        total_quests = len(all_logs)
        completed = sum(1 for l in all_logs if l.get("status") == "success")
        failed = sum(1 for l in all_logs if l.get("status") == "failed")
        
        return jsonify({
            "success": True,
            "message": f"Thống kê Quest\n📊 Tổng: {total_quests}\n✅ Hoàn thành: {completed}\n❌ Thất bại: {failed}",
            "stats": {
                "total": total_quests,
                "completed": completed,
                "failed": failed,
                "running_accounts": len(running_accounts)
            }
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Lỗi: {str(e)}"})

@app.route("/api/stop-quest", methods=["POST"])
def api_stop_quest():
    """Handle Stop Quest"""
    try:
        all_workers = get_all_workers()
        stopped_count = 0
        
        for worker in all_workers:
            if worker:
                user_id = worker.get("user_id")
                stop_worker(user_id)
                stopped_count += 1
        
        if stopped_count > 0:
            return jsonify({
                "success": True,
                "message": f"Dừng phiên hiện tại\n⏹ Đã dừng {stopped_count} tài khoản"
            })
        else:
            return jsonify({
                "success": False,
                "message": "⚠️ Không có quest nào đang chạy!"
            })
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ Lỗi: {str(e)}"})

# ── Helpers ──────────────────────────────────────────────────────────────────
def action_emoji(action: str) -> str:
    return {"enrolled": "📋", "completed": "✅", "failed": "❌", "pending": "⏳"}.get(action, "❓")

# ── Modal & Views ────────────────────────────────────────────────────────────

class TokenInputModal(discord.ui.Modal, title="Nhập Token Discord"):
    token_input = discord.ui.TextInput(
        label="TOKEN", 
        placeholder="Dán token Discord của bạn tại đây", 
        min_length=50, 
        style=discord.TextStyle.long
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        token = self.token_input.value.strip()
        try:
            database.add_account(token)
            accounts = database.get_all_accounts()
            account = next((a for a in accounts if a.get("token") == token), None)
            
            user_id = account["user_id"]
            username = account.get("username") or account.get("global_name") or user_id[:12]
            token_to_user[token] = {"discord_user_id": interaction.user.id, "user_id": user_id, "username": username}
            
            if not get_worker(user_id):
                start_worker(token, user_id, username, 60, True)
                await interaction.response.send_message(
                    f"🛡️ Thêm và khởi chạy thành công!\n\n👤 Tài khoản: **{username}**\n⚡ Trạng thái: `🟢 Đang chạy`",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"🛡️ Thêm thành công tài khoản: **{username}**\n⚠️ Nhưng tài khoản này đã chạy rồi!",
                    ephemeral=True
                )
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi: {e}", ephemeral=True)

class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Auto Quest", style=discord.ButtonStyle.primary, emoji="🔑")
    async def auto_quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TokenInputModal())

    @discord.ui.button(label="Thống kê Quest", style=discord.ButtonStyle.secondary, emoji="💎")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens_map = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens_map:
            await interaction.followup.send("❌ Bạn chưa nhập token nào!", ephemeral=True)
            return

        stats = database.get_stats()
        running_accounts = get_running_accounts()
        
        embed = discord.Embed(title="💎 THỐNG KÊ QUEST", color=0x9B59B6)
        
        for token, info in user_tokens_map.items():
            u_id = info["user_id"]
            uname = info["username"]
            
            is_running = get_worker(u_id) is not None
            status_text = "🟢 Đang chạy" if is_running else "🔴 Đang dừng"
            
            token_logs = database.get_quest_logs_by_user(u_id, 10)
            total = len(token_logs)
            enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
            failed = sum(1 for l in token_logs if l.get("status") == "failed")
            completed = sum(1 for l in token_logs if l.get("status") == "success")
            
            field_value = (
                f"🔹 **Trạng Thái**: `{status_text}`\n"
                f"📊 **Tổng quest**: `{total}`\n"
                f"✅ **Hoàn thành**: `{completed}`\n"
                f"📥 **Đã nhận**: `{enrolled}`\n"
                f"❌ **Thất bại**: `{failed}`"
            )
            embed.add_field(name=f"👤 {uname}", value=field_value, inline=False)
        
        embed.set_footer(text="⚡ Oni • Quest Auto-Completer")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="Stop Quest", style=discord.ButtonStyle.danger, emoji="⏹")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens = [v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        
        if not user_tokens:
            await interaction.followup.send("❌ Không có token nào!", ephemeral=True)
            return

        stopped = []
        for info in user_tokens:
            if get_worker(info["user_id"]):
                stop_worker(info["user_id"])
                stopped.append(info["username"])
                
        if stopped:
            await interaction.followup.send(f"⏹ Đã dừng: **{', '.join(stopped)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có quest nào đang chạy!", ephemeral=True)

# ── Discord Commands ─────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="⚡ Oni Quest Control Panel")
async def autoquest(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔑 QUEST AUTO-COMPLETER",
        description="Chào mừng đến với Quest Auto-Completer!\nNhấn nút bên dưới để quản lý quest của bạn.",
        color=0x9B59B6
    )
    
    embed.add_field(name="🔑 Auto Quest", value="Bắt đầu hoàn thành quest tự động", inline=False)
    embed.add_field(name="💎 Thống kê Quest", value="Xem Quest đã làm, chưa làm, Orbs đã nhận", inline=False)
    embed.add_field(name="⏹ Stop Quest", value="Dừng phiên hiện tại", inline=False)
    embed.add_field(name="⚠️ Ghi chú", value="Token chỉ dùng để hoàn thành quest, không lưu trữ.", inline=False)
    embed.set_footer(text="By: Oni • Quest Auto-Completer")
    
    await interaction.response.send_message(embed=embed, view=ControlPanelView(), ephemeral=False)

@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"✅ Bot online: {bot.user}")

# ── Start Flask Server ────────────────────────────────────────────────────────
def run_flask():
    """Run Flask web server"""
    app.run(host="0.0.0.0", port=5000, debug=False)

def run_bot():
    """Run Discord Bot"""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        # Chạy Flask trong thread riêng
        flask_thread = Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Chạy Discord Bot
        bot.run(token)
    else:
        log.error("DISCORD_BOT_TOKEN không được tìm thấy cho bot!")

if __name__ == "__main__":
    run_bot()
