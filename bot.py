"""
Quest Auto-Completer Bot - Refactored
Modal-based UI with per-token status tracking & channel notifications
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
log = logging.getLogger("quest_bot")

# ── Config ───────────────────────────────────────────────────────────────────

NOTIFICATION_CHANNEL_ID = int(os.environ.get("NOTIFICATION_CHANNEL_ID", "0")) or None
POLL_INTERVAL_DEFAULT = int(os.environ.get("POLL_INTERVAL", "60"))

# ── Bot Setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Track token → user mapping (for per-user status)
token_to_user = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def account_status_emoji(status: str) -> str:
    return {"running": "🟢", "offline": "⚫", "idle": "🟡"}.get(status, "⚪")


def get_quest_stats_by_token(token: str) -> dict:
    """Get stats for a specific token"""
    accounts = database.get_all_accounts()
    account = next((a for a in accounts if a.get("token") == token), None)
    if not account:
        return None
    
    # Get logs for this account (filter by user_id, not token)
    user_id = account.get("user_id")
    all_logs = database.get_stats().get("recent_logs", [])
    token_logs = [l for l in all_logs if l.get("user_id") == user_id]
    
    total = len(token_logs)
    completed = sum(1 for l in token_logs if l.get("status") == "success" and l.get("action") == "completed")
    enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
    failed = sum(1 for l in token_logs if l.get("status") == "failed")
    
    return {
        "username": account.get("username") or account.get("global_name") or account.get("user_id")[:12],
        "user_id": account.get("user_id"),
        "total": total,
        "completed": completed,
        "enrolled": enrolled,
        "failed": failed,
        "percentage": int((completed / enrolled * 100)) if enrolled > 0 else 0,
        "recent_logs": token_logs[:15]
    }


# ── Modal Input ───────────────────────────────────────────────────────────────

class TokenInputModal(discord.ui.Modal, title="Quest Auto-Completer"):
    token_input = discord.ui.TextInput(
        label="Discord Token",
        placeholder="Dán token Discord của bạn tại đây",
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
            account_id = database.add_account(token)
            accounts = database.get_all_accounts()
            account = next((a for a in accounts if a.get("token") == token), None)
            
            if not account:
                await interaction.response.send_message("❌ Không tìm thấy tài khoản sau khi thêm.", ephemeral=True)
                return
            
            user_id = account["user_id"]
            username = account.get("username") or account.get("global_name") or user_id[:12]
            
            # Store token → user mapping
            token_to_user[token] = {
                "discord_user_id": interaction.user.id,
                "user_id": user_id,
                "username": username
            }
            
            # Show action buttons
            view = QuestActionView(token, username, user_id)
            embed = discord.Embed(
                title="✅ Token Được Thêm",
                description=f"**{username}** sẵn sàng!",
                color=0x00FF88
            )
            embed.add_field(name="Status", value="⏸️ Chờ bạn chọn action...", inline=False)
            
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi: {str(e)[:100]}", ephemeral=True)


# ── Persistent View (Buttons) ─────────────────────────────────────────────────

class QuestActionView(discord.ui.View):
    def __init__(self, token: str, username: str, user_id: str):
        super().__init__(timeout=None)
        self.token = token
        self.username = username
        self.user_id = user_id
    
    @discord.ui.button(label="⚡ Auto Quest", style=discord.ButtonStyle.primary, emoji="⚡")
    async def auto_quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        if get_worker(self.user_id):
            await interaction.followup.send(
                f"⚠️ `{self.username}` đang chạy rồi!",
                ephemeral=True
            )
            return
        
        def start_and_log():
            start_worker(self.token, self.user_id, self.username, POLL_INTERVAL_DEFAULT, True)
            log.info(f"✅ Started quest for {self.username}")
        
        import threading
        threading.Thread(target=start_and_log, daemon=True).start()
        
        embed = discord.Embed(
            title="🚀 Quest Started",
            description=f"Đã bắt đầu auto quest cho **{self.username}**",
            color=0x00FF88
        )
        embed.add_field(name="Poll Interval", value=f"{POLL_INTERVAL_DEFAULT}s", inline=True)
        embed.add_field(name="Status", value="🟢 Running", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="📊 Status", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        stats = get_quest_stats_by_token(self.token)
        if not stats:
            await interaction.followup.send("❌ Không tìm thấy dữ liệu.", ephemeral=True)
            return
        
        worker = get_worker(self.user_id)
        status = "🟢 Chạy" if worker else "⚫ Offline"
        
        embed = discord.Embed(
            title=f"📊 Status - {stats['username']}",
            color=0x5865F2
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Tổng Quest", value=str(stats['total']), inline=True)
        embed.add_field(name="Hoàn Thành", value=f"{stats['completed']}/{stats['enrolled']}", inline=True)
        embed.add_field(name="Thất Bại", value=str(stats['failed']), inline=True)
        embed.add_field(name="% Hoàn Thành", value=f"{stats['percentage']}%", inline=True)
        
        # Show current active quest if running
        if worker and hasattr(worker, 'current_quest'):
            embed.add_field(
                name="🎯 Quest Đang Làm",
                value=worker.current_quest or "Tìm quest...",
                inline=False
            )
        
        if stats['recent_logs']:
            lines = []
            for log in stats['recent_logs'][:8]:
                emoji = "✅" if log.get("status") == "success" else "❌"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id', '?')}"
                lines.append(f"{emoji} {qname}")
            embed.add_field(name="Quest Gần Đây", value="\n".join(lines), inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="⛔ Stop Quest", style=discord.ButtonStyle.danger, emoji="⛔")
    async def stop_quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        stop_worker(self.user_id)
        
        embed = discord.Embed(
            title="✅ Đã Dừng",
            description=f"Dừng quest cho **{self.username}**",
            color=0xFF5555
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Slash Commands ────────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="Quản lý auto quest - nhập token và chọn action")
async def autoquest_command(interaction: discord.Interaction):
    """Main command - open modal"""
    await interaction.response.send_modal(TokenInputModal())


@tree.command(name="status", description="Xem status tất cả token của bạn")
async def status_all_command(interaction: discord.Interaction):
    """Show status for all tokens of this user in one message"""
    await interaction.response.defer(ephemeral=True)
    
    # Find all tokens registered by this user
    user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
    
    if not user_tokens:
        await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
        return
    
    embeds = []
    
    for token in user_tokens:
        stats = get_quest_stats_by_token(token)
        if not stats:
            continue
        
        worker = get_worker(stats['user_id'])
        status = "🟢 Chạy" if worker else "⚫ Offline"
        
        embed = discord.Embed(
            title=f"📊 {stats['username']}",
            color=0x5865F2 if worker else 0x666666
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Hoàn Thành", value=f"{stats['completed']}/{stats['enrolled']}", inline=True)
        embed.add_field(name="% Hoàn", value=f"{stats['percentage']}%", inline=True)
        embed.add_field(name="Thất Bại", value=str(stats['failed']), inline=True)
        embed.add_field(name="Tổng Quest", value=str(stats['total']), inline=True)
        
        # Show active quest if running
        if worker and hasattr(worker, 'current_quest'):
            embed.add_field(
                name="🎯 Quest Đang Làm",
                value=worker.current_quest or "Tìm quest...",
                inline=False
            )
        
        if stats['recent_logs']:
            lines = []
            for log in stats['recent_logs'][:5]:
                emoji = "✅" if log.get("status") == "success" else "❌"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id', '?')}"
                lines.append(f"{emoji} {qname}")
            embed.add_field(name="Quest Gần Đây", value="\n".join(lines), inline=False)
        
        embeds.append(embed)
    
    if not embeds:
        await interaction.followup.send("❌ Không tìm thấy dữ liệu!", ephemeral=True)
        return
    
    # Send all embeds in one message (Discord allows up to 10 embeds per message)
    await interaction.followup.send(embeds=embeds)


@tree.command(name="setchannel", description="Setup channel để nhận thông báo quest complete")
@app_commands.describe(channel="Channel để nhận thông báo")
async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set notification channel"""
    os.environ["NOTIFICATION_CHANNEL_ID"] = str(channel.id)
    
    embed = discord.Embed(
        title="✅ Channel Được Setup",
        description=f"Thông báo sẽ được gửi vào {channel.mention}",
        color=0x00FF88
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="help", description="Hướng dẫn sử dụng")
async def help_command(interaction: discord.Interaction):
    """Show help"""
    embed = discord.Embed(
        title="📖 Hướng Dẫn Sử Dụng",
        description="Quest Auto-Completer Bot",
        color=0x5865F2
    )
    
    embed.add_field(
        name="`/autoquest`",
        value="Nhập token Discord và chọn action (Auto Quest, Status, Stop)",
        inline=False
    )
    embed.add_field(
        name="`/status`",
        value="Xem status tất cả token của bạn (hiển thị riêng từng token)",
        inline=False
    )
    embed.add_field(
        name="`/setchannel <channel>`",
        value="Setup channel để nhận thông báo khi quest complete",
        inline=False
    )
    
    embed.add_field(
        name="⚠️ Lưu Ý",
        value="Token là mật khẩu của tài khoản Discord. Không chia sẻ với ai!",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=False)


# ── Background Task - Send Completion Notifications ───────────────────────────

@tasks.loop(seconds=30)
async def send_quest_notifications():
    """Check for completed quests and notify"""
    if not NOTIFICATION_CHANNEL_ID:
        return
    
    try:
        channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
        if not channel:
            return
        
        stats = database.get_stats()
        recent = stats.get("recent_logs", [])
        
        # Get last checked timestamp
        last_notified = getattr(send_quest_notifications, "last_notified", set())
        
        for log in recent:
            log_id = f"{log.get('quest_id')}_{log.get('token')}"
            
            if log_id in last_notified:
                continue
            
            if log.get("action") == "completed" and log.get("status") == "success":
                # Find user for this token
                user_info = None
                for token, info in token_to_user.items():
                    if info.get("user_id") == log.get("user_id"):
                        user_info = info
                        break
                
                username = user_info["username"] if user_info else "Unknown"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id')}"
                
                embed = discord.Embed(
                    title="🎉 Quest Hoàn Thành!",
                    description=f"**{username}** vừa hoàn thành quest",
                    color=0x00FF88
                )
                embed.add_field(name="Quest", value=qname, inline=False)
                
                await channel.send(embed=embed)
                last_notified.add(log_id)
        
        send_quest_notifications.last_notified = last_notified
    
    except Exception as e:
        log.error(f"Error in notification task: {e}")


# ── Bot Events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info(f"✅ Bot Online: {bot.user} (ID: {bot.user.id})")
    await tree.sync()
    log.info("🔧 Commands Synced")
    
    if not send_quest_notifications.is_running():
        send_quest_notifications.start()


# ── Run Bot ───────────────────────────────────────────────────────────────────

def run_bot():
    """Start the bot"""
    database.init_db()
    log.info("📦 Database Initialized")
    
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN not set!")
        print("❌ DISCORD_BOT_TOKEN not set in .env!")
        return
    
    log.info("🚀 Starting Quest Bot...")
    bot.run(token)


if __name__ == "__main__":
    run_bot()

