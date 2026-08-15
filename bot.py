"""
Quest Auto-Completer Bot - Control Panel Version (ONI QUEST Custom)
All-in-one /autoquest command with button controls & token-specific stats
"""

import os
import sys
import logging
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands, tasks
import database
from worker import start_worker, stop_worker, get_worker, get_all_workers, get_running_accounts

# ── Logging ──────────────────────────────────────────────────────────────────

LOG_FILE = "quest_bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("oni_quest_bot")

# ── Config ───────────────────────────────────────────────────────────────────

NOTIFICATION_CHANNEL_ID = int(os.environ.get("NOTIFICATION_CHANNEL_ID", "0")) or None
POLL_INTERVAL_DEFAULT = int(os.environ.get("POLL_INTERVAL", "60"))

# ── Bot Setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Track token → user mapping (hỗ trợ 1 user nhập nhiều token)
token_to_user = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def action_emoji(action: str) -> str:
    return {"enrolled": "📥", "completed": "🏆", "failed": "❌", "pending": "⏳"}.get(action, "❓")


# ── Modal Input ───────────────────────────────────────────────────────────────

class TokenInputModal(discord.ui.Modal, title="Nhập Token Discord"):
    token_input = discord.ui.TextInput(
        label="TOKEN",
        placeholder="Dán token của bạn tại đây (Hỗ trợ nhiều token)",
        min_length=50,
        max_length=200,
        style=discord.TextStyle.long
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        token = self.token_input.value.strip()
        
        if not token or len(token) < 50:
            await interaction.response.send_message("❌ Token không hợp lệ!", ephemeral=True)
            return
        
        try:
            database.add_account(token)
            accounts = database.get_all_accounts()
            account = next((a for a in accounts if a.get("token") == token), None)
            
            if not account:
                await interaction.response.send_message("❌ Không tìm thấy tài khoản sau khi thêm.", ephemeral=True)
                return
            
            user_id = account["user_id"]
            username = account.get("username") or account.get("global_name") or user_id[:12]
            
            # Lưu lại mapping token theo discord user id
            token_to_user[token] = {
                "discord_user_id": interaction.user.id,
                "user_id": user_id,
                "username": username
            }
            
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(
                f"🛡️ Thêm thành công tài khoản: **{username}**",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi: {str(e)[:100]}", ephemeral=True)


# ── Control Panel Buttons ─────────────────────────────────────────────────────

class ControlPanelView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
    
    @discord.ui.button(label="Nhập Token", style=discord.ButtonStyle.primary, emoji="🔑")
    async def token_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TokenInputModal())
    
    @discord.ui.button(label="Bắt Đầu", style=discord.ButtonStyle.success, emoji="⚡")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        
        if not user_tokens:
            await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
            return
        
        started = []
        for token in user_tokens:
            user_info = token_to_user[token]
            user_id = user_info["user_id"]
            username = user_info["username"]
            
            if get_worker(user_id):
                continue
            
            def start_worker_thread():
                start_worker(token, user_id, username, POLL_INTERVAL_DEFAULT, True)
            
            import threading
            threading.Thread(target=start_worker_thread, daemon=True).start()
            started.append(username)
        
        if started:
            await interaction.followup.send(f"⚡ Đã khởi chạy autoquest cho: **{', '.join(started)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Tất cả token của bạn đã chạy rồi!", ephemeral=True)
    
    @discord.ui.button(label="Dừng Quest", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        
        if not user_tokens:
            await interaction.followup.send("❌ Không có token nào!", ephemeral=True)
            return
        
        stopped = []
        for token in user_tokens:
            user_info = token_to_user[token]
            user_id = user_info["user_id"]
            username = user_info["username"]
            
            if get_worker(user_id):
                stop_worker(user_id)
                stopped.append(username)
        
        if stopped:
            await interaction.followup.send(f"⏹️ Đã dừng hệ thống của: **{', '.join(stopped)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có token nào của bạn đang chạy!", ephemeral=True)
    
    @discord.ui.button(label="Trạng Thái", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Lấy danh sách token cụ thể do Discord user này nhập
        user_tokens_map = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens_map:
            await interaction.followup.send("❌ Bạn chưa nhập token nào vào hệ thống để thống kê!", ephemeral=True)
            return

        stats = database.get_stats()
        all_logs = stats.get("recent_logs", [])
        
        embed = discord.Embed(title="🛡️ ONI QUEST - THỐNG KÊ CÁ NHÂN", color=0x9B59B6)
        
        # Duyệt riêng từng token/tài khoản mà user này đã nhập
        for token, info in user_tokens_map.items():
            u_id = info["user_id"]
            uname = info["username"]
            
            # Lọc log riêng cho từng user_id của token đó
            token_logs = [l for l in all_logs if l.get("user_id") == u_id]
            
            total = len(token_logs)
            enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
            failed = sum(1 for l in token_logs if l.get("status") == "failed")
            is_active = "🟢 Đang chạy" if get_worker(u_id) else "🔴 Đang dừng"
            
            # Xây dựng chuỗi hiển thị quest gần đây cho riêng tài khoản này
            if token_logs:
                lines = []
                for log_entry in token_logs[:5]:  # Hiển thị tối đa 5 quest gần nhất mỗi nick cho gọn
                    act_icon = action_emoji(log_entry.get("action", ""))
                    stat_icon = "✅" if log_entry.get("status") == "success" else "❌"
                    qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
                    lines.append(f"{act_icon} {stat_icon} **{qname}**")
                recent_str = "\n".join(lines)
            else:
                recent_str = "Chưa có hoạt động quest nào."
            
            # Đóng gói thông tin thành Field riêng biệt cho mỗi token
            field_value = (
                f"🔹 **Trạng Thái**: `{is_active}`\n"
                f"📊 **Tổng quest**: `{total}`\n"
                f"📥 **Đã nhận**: `{enrolled}`\n"
                f"❌ **Thất bại**: `{failed}`\n"
                f"📜 **Quest gần đây**:\n{recent_str}"
            )
            embed.add_field(name=f"👤 Tài khoản: {uname}", value=field_value, inline=False)
        
        embed.set_footer(text="⚡ ONI QUEST SYSTEM • High Performance Auto-Completer")
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Hướng Dẫn", style=discord.ButtonStyle.secondary, emoji="🧭")
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="🧭 HƯỚNG DẪN SỬ DỤNG ONI QUEST",
            description="Hệ thống tự động hoàn thành Quest Discord chuyên nghiệp",
            color=0x9B59B6
        )
        embed.add_field(name="🔑 Nhập Token", value="Thêm một hoặc nhiều token Discord của bạn vào hệ thống an toàn.", inline=False)
        embed.add_field(name="⚡ Bắt Đầu", value="Kích hoạt luồng tự động làm quest cho toàn bộ token bạn đã thêm.", inline=False)
        embed.add_field(name="⏹️ Dừng Quest", value="Tạm dừng toàn bộ các tiến trình đang chạy của bạn.", inline=False)
        embed.add_field(name="📊 Trạng Thái", value="Hiểm thị bảng thống kê chi tiết tách biệt theo từng tài khoản token.", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Slash Commands ────────────────────────────────____________________________

@tree.command(name="autoquest", description="⚡ ONI QUEST Control Panel - All-in-One")
async def autoquest_command(interaction: discord.Interaction):
    """Main control panel command"""
    embed = discord.Embed(
        title="⚡ ONI QUEST MANAGER",
        description="Bảng điều khiển hệ thống Auto Quest độc quyền",
        color=0x9B59B6
    )
    embed.add_field(name="🛡️ Trạng thái hệ thống", value="`🟢 Sẵn sàng hoạt động`", inline=False)
    embed.add_field(name="⚙️ Thao tác nhanh", value="Sử dụng các nút bên dưới để cấu hình và điều khiển bot.", inline=False)
    
    view = ControlPanelView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


@tree.command(name="status", description="Xem status tổng quan hệ thống toàn bộ bot")
async def status_command(interaction: discord.Interaction):
    """Show global status"""
    await interaction.response.defer(ephemeral=True)
    
    workers = get_all_workers()
    running_count = len(workers)
    
    stats = database.get_stats()
    recent = stats.get("recent_logs", [])[:10]
    failed = sum(1 for l in recent if l.get("status") == "failed")
    
    embed = discord.Embed(title="📊 ONI QUEST - GLOBAL STATISTICS", color=0x9B59B6)
    embed.add_field(name="📈 Tổng quest hệ thống", value=str(stats.get("total_logs", 0)), inline=False)
    embed.add_field(name="📥 Tổng đã nhận", value=str(stats.get("enrolled_logs", 0)), inline=False)
    embed.add_field(name="⚡ Active workers", value=str(running_count), inline=False)

    if recent:
        lines = []
        for log_entry in recent[:10]:
            action_icon = action_emoji(log_entry.get("action", ""))
            status_icon = "✅" if log_entry.get("status") == "success" else "❌"
            qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
            lines.append(f"{action_icon} {status_icon} **{qname}**")
        embed.add_field(name="📜 Quest gần đây toàn cục", value="\n".join(lines) or "—", inline=False)
    else:
        embed.add_field(name="📜 Quest gần đây toàn cục", value="—", inline=False)

    embed.set_footer(text=f"Total Enrolled: {stats.get('enrolled_logs', 0)} | Failed: {failed}")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="setchannel", description="Setup channel thông báo (Admin only)")
@app_commands.describe(channel="Channel để nhận thông báo")
async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Chỉ admin mới có quyền thực hiện lệnh này!", ephemeral=True)
        return
    
    os.environ["NOTIFICATION_CHANNEL_ID"] = str(channel.id)
    embed = discord.Embed(title="🛡️ Thiết Lập Thành Công", description=f"Kênh thông báo quest đã được chuyển tới {channel.mention}", color=0x00FF88)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Background Task ───────────────────────────────────────────────────────────

@tasks.loop(seconds=30)
async def send_quest_notifications():
    if not NOTIFICATION_CHANNEL_ID:
        return
    try:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if not channel:
            return
        
        stats = database.get_stats()
        recent = stats.get("recent_logs", [])
        last_notified = getattr(send_quest_notifications, "last_notified", set())
        
        for log in recent:
            log_id = f"{log.get('quest_id')}_{log.get('user_id')}"
            if log_id in last_notified:
                continue
            
            if log.get("action") == "completed" and log.get("status") == "success":
                user_info = next((info for token, info in token_to_user.items() if info.get("user_id") == log.get("user_id")), None)
                username = user_info["username"] if user_info else "Unknown"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id')}"
                
                embed = discord.Embed(title="🏆 ONI QUEST - HOÀN THÀNH NHIỆM VỤ", description=f"Tài khoản: **{username}**", color=0x00FF88)
                embed.add_field(name="🎯 Tên Quest", value=qname, inline=False)
                embed.set_footer(text=f"Thời gian: {log.get('timestamp', '')}")
                
                await channel.send(embed=embed)
                last_notified.add(log_id)
        
        send_quest_notifications.last_notified = last_notified
    except Exception as e:
        log.error(f"Error in notification task: {e}")


# ── Bot Events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info(f"🛡️ ONI QUEST Bot online: {bot.user} (ID: {bot.user.id})")
    await tree.sync()
    log.info("⚙️ Slash Commands synchronized successfully.")
    
    if not send_quest_notifications.is_running():
        send_quest_notifications.start()


# ── Run Bot ───────────────────────────────────────────────────────────────────

def run_bot():
    database.init_db()
    log.info("📦 Database Initialized")
    
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN not set!")
        print("❌ DISCORD_BOT_TOKEN not set in .env!")
        return
    
    log.info("🚀 Starting ONI QUEST Bot...")
    bot.run(token)


if __name__ == "__main__":
    run_bot()

