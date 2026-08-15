"""
Quest Auto-Completer Bot - Control Panel Version
All-in-one /autoquest command with button controls
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

# Track token → user mapping
token_to_user = {}
user_message_id = {}  # Track message ID per user


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_quest_stats_by_token(token: str) -> dict:
    """Get stats for a specific token"""
    accounts = database.get_all_accounts()
    account = next((a for a in accounts if a.get("token") == token), None)
    if not account:
        return None
    
    user_id = account.get("user_id")
    all_logs = database.get_stats().get("recent_logs", [])
    token_logs = [l for l in all_logs if l.get("user_id") == user_id]
    
    total = len(token_logs)
    completed = sum(1 for l in token_logs if l.get("status") == "success" and l.get("action") == "completed")
    enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
    failed = sum(1 for l in token_logs if l.get("status") == "failed")
    
    running_accounts = get_running_accounts()
    current_quest = None
    is_running = False
    
    for acc in running_accounts:
        if acc.get("user_id") == user_id:
            current_quest = acc.get("current_quest")
            is_running = True
            break
    
    return {
        "username": account.get("username") or account.get("global_name") or account.get("user_id")[:12],
        "user_id": account.get("user_id"),
        "total": total,
        "completed": completed,
        "enrolled": enrolled,
        "failed": failed,
        "percentage": int((completed / enrolled * 100)) if enrolled > 0 else 0,
        "recent_logs": token_logs[:15],
        "current_quest": current_quest,
        "is_running": is_running
    }


# ── Modal Input ───────────────────────────────────────────────────────────────

class TokenInputModal(discord.ui.Modal, title="Nhập Token Discord"):
    token_input = discord.ui.TextInput(
        label="TOKEN",
        placeholder="Dán token của bạn tại đây",
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
            
            token_to_user[token] = {
                "discord_user_id": interaction.user.id,
                "user_id": user_id,
                "username": username
            }
            
            await interaction.response.defer(ephemeral=True)
            await interaction.followup.send(
                f"✅ Token thêm thành công: **{username}**",
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
    
    @discord.ui.button(label="Bắt Đầu", style=discord.ButtonStyle.success, emoji="▶️")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Get user's tokens
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
            await interaction.followup.send(f"✅ Bắt đầu: **{', '.join(started)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Tất cả token đã chạy rồi!", ephemeral=True)
    
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
            await interaction.followup.send(f"✅ Đã dừng: **{', '.join(stopped)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có token nào đang chạy!", ephemeral=True)
    
    @discord.ui.button(label="Trạng Thái", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        
        if not user_tokens:
            await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
            return
        
        embeds = []
        for token in user_tokens:
            stats = get_quest_stats_by_token(token)
            if not stats:
                continue
            
            status = "🟢 Online" if stats['is_running'] else "⚫ Offline"
            
            embed = discord.Embed(
                title=f"📊 {stats['username']}",
                color=0x5865F2 if stats['is_running'] else 0x666666,
                description=status
            )
            
            if stats['is_running'] and stats['current_quest']:
                embed.add_field(
                    name="⚡ ACTIVE QUEST",
                    value=f"```{stats['current_quest']}```",
                    inline=False
                )
            
            stats_line = f"◈Hoàn Thành: **{stats['completed']}** | ◈Thất Bại: **{stats['failed']}** | ◈All Quest: **{stats['enrolled']}**"
            embed.add_field(name="━━━━━━━━━━━━━━", value=stats_line, inline=False)
            
            if stats['recent_logs']:
                recent_lines = []
                for log in stats['recent_logs'][:10]:
                    emoji = "✅" if log.get("status") == "success" else "❌"
                    qname = log.get("quest_name") or f"Quest#{log.get('quest_id', '?')}"
                    recent_lines.append(f"{emoji} {qname}")
                
                quest_text = "\n".join(recent_lines) if recent_lines else "—"
                embed.add_field(name="◈Quest Hoàn Thành", value=quest_text, inline=False)
            
            embed.set_footer(text="━━━━━━━━━━━━━━━")
            embeds.append(embed)
        
        if embeds:
            await interaction.followup.send(embeds=embeds, ephemeral=True)
        else:
            await interaction.followup.send("❌ Không tìm thấy dữ liệu!", ephemeral=True)
    
    @discord.ui.button(label="Hướng Dẫn", style=discord.ButtonStyle.secondary, emoji="❓")
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="❓ Hướng Dẫn",
            description="Cách sử dụng Quest Manager",
            color=0x5865F2
        )
        
        embed.add_field(
            name="🔑 Nhập Token",
            value="Nhấn nút này để thêm token Discord của bạn",
            inline=False
        )
        embed.add_field(
            name="▶️ Bắt Đầu",
            value="Bắt đầu tự động hoàn thành quest cho tất cả token",
            inline=False
        )
        embed.add_field(
            name="⏹️ Dừng Quest",
            value="Dừng quá trình tự động hoàn thành",
            inline=False
        )
        embed.add_field(
            name="📊 Trạng Thái",
            value="Xem chi tiết status của từng token",
            inline=False
        )
        embed.add_field(
            name="⚠️ Lưu Ý",
            value="Token là mật khẩu của tài khoản. Không chia sẻ với ai!",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Slash Commands ────────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="⚡ Quest Control Panel - All-in-One")
async def autoquest_command(interaction: discord.Interaction):
    """Main control panel command"""
    
    # Get system status
    running_accounts = get_running_accounts()
    system_status = "🟢 Online" if running_accounts else "🟢 Online"
    
    embed = discord.Embed(
        title="⚡ QUEST MANAGER",
        description="Discord Quest Control Panel",
        color=0x5865F2
    )
    
    embed.add_field(name="🟢 System", value=system_status, inline=False)
    embed.add_field(name="🔧 Status", value="Ready", inline=False)
    
    embed.add_field(
        name="⚙️ Control Panel",
        value="Sử dụng các nút bên dưới để quản lý bot",
        inline=False
    )
    embed.add_field(
        name="🔑 TOKEN",
        value="Not configured",
        inline=False
    )
    embed.add_field(
        name="📊 Status",
        value="Ready",
        inline=False
    )
    embed.add_field(
        name="⚡ Mode",
        value="Active",
        inline=False
    )
    
    embed.set_footer(text="Quest Manager • Discord Bot")
    
    view = ControlPanelView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)


@tree.command(name="status", description="Xem status tất cả token của bạn")
async def status_command(interaction: discord.Interaction):
    """Show detailed status for all tokens"""
    await interaction.response.defer(ephemeral=True)
    
    user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
    
    if not user_tokens:
        await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
        return
    
    embeds = []
    
    for token in user_tokens:
        stats = get_quest_stats_by_token(token)
        if not stats:
            continue
        
        status = "🟢 Online" if stats['is_running'] else "⚫ Offline"
        
        embed = discord.Embed(
            title=f"📊 {stats['username']}",
            color=0x5865F2 if stats['is_running'] else 0x666666,
            description=status
        )
        
        if stats['is_running'] and stats['current_quest']:
            embed.add_field(
                name="⚡ ACTIVE QUEST",
                value=f"```{stats['current_quest']}```",
                inline=False
            )
        
        stats_line = f"◈Hoàn Thành: **{stats['completed']}** | ◈Thất Bại: **{stats['failed']}** | ◈All Quest: **{stats['enrolled']}**"
        embed.add_field(name="━━━━━━━━━━━━━━", value=stats_line, inline=False)
        
        if stats['recent_logs']:
            recent_lines = []
            for log in stats['recent_logs'][:10]:
                emoji = "✅" if log.get("status") == "success" else "❌"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id', '?')}"
                recent_lines.append(f"{emoji} {qname}")
            
            quest_text = "\n".join(recent_lines) if recent_lines else "—"
            embed.add_field(name="◈Quest Hoàn Thành", value=quest_text, inline=False)
        
        embed.set_footer(text="━━━━━━━━━━━━━━━")
        embeds.append(embed)
    
    if embeds:
        await interaction.followup.send(embeds=embeds)
    else:
        await interaction.followup.send("❌ Không tìm thấy dữ liệu!", ephemeral=True)


@tree.command(name="setchannel", description="Setup channel thông báo (Admin only)")
@app_commands.describe(channel="Channel để nhận thông báo")
async def setchannel_command(interaction: discord.Interaction, channel: discord.TextChannel):
    """Set notification channel (admin only)"""
    
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Chỉ admin mới có quyền!", ephemeral=True)
        return
    
    os.environ["NOTIFICATION_CHANNEL_ID"] = str(channel.id)
    
    embed = discord.Embed(
        title="✅ Channel Được Setup",
        description=f"Thông báo sẽ được gửi vào {channel.mention}",
        color=0x00FF88
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


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
        
        last_notified = getattr(send_quest_notifications, "last_notified", set())
        
        for log in recent:
            log_id = f"{log.get('quest_id')}_{log.get('user_id')}"
            
            if log_id in last_notified:
                continue
            
            if log.get("action") == "completed" and log.get("status") == "success":
                user_info = None
                for token, info in token_to_user.items():
                    if info.get("user_id") == log.get("user_id"):
                        user_info = info
                        break
                
                username = user_info["username"] if user_info else "Unknown"
                qname = log.get("quest_name") or f"Quest#{log.get('quest_id')}"
                
                embed = discord.Embed(
                    title="🎉 QUEST HOÀN THÀNH",
                    description=f"**{username}**",
                    color=0x00FF88
                )
                embed.add_field(name="◈Quest", value=qname, inline=False)
                embed.set_footer(text=f"Thời gian: {log.get('timestamp', '')}")
                
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

