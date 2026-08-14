"""
Henxi - Discord Quest Auto-Completer Bot
Chỉ chứa logic auto quest, không có dashboard.
"""

import os
import sys
import logging

import discord
from discord import app_commands
from discord.ext import commands

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
log = logging.getLogger("henxi")


# ── Bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ── Helpers ───────────────────────────────────────────────────────────────────

def account_status_emoji(status: str) -> str:
    return {"running": "🟢", "offline": "⚫", "idle": "🟡"}.get(status, "⚪")


def action_emoji(action: str) -> str:
    return {"enrolled": "📋", "completed": "✅", "failed": "❌", "pending": "⏳"}.get(action, "❓")


# ── Slash Commands ───────────────────────────────────────────────────────────

@tree.command(name="quest", description="Them token & bat dau auto quest ngay lap tuc")
@app_commands.describe(
    token="Discord Token cua ban",
    poll_interval="Thoi gian quet (giay, mac dinh 60)"
)
async def quest_command(interaction: discord.Interaction, token: str, poll_interval: int = 60):
    await interaction.response.defer(ephemeral=True)

    if not token or len(token) < 50:
        await interaction.followup.send("❌ Token khong hop le.", ephemeral=True)
        return

    try:
        account_id = database.add_account(token)
    except Exception as e:
        await interaction.followup.send(f"❌ Loi khi them tai khoan: {e}", ephemeral=True)
        return

    accounts = database.get_all_accounts()
    account = next((a for a in accounts if a.get("token") == token), None)
    if not account:
        await interaction.followup.send("❌ Khong tim thay tai khoan sau khi them.", ephemeral=True)
        return

    user_id = account["user_id"]
    username = account.get("username") or account.get("global_name") or user_id[:12]

    if get_worker(user_id):
        await interaction.followup.send(
            f"⚠️ `{username}` dang chay roi! Dung `/stopquest {user_id}` de dung truoc.",
            ephemeral=True
        )
        return

    if poll_interval < 10:
        poll_interval = 10
    elif poll_interval > 600:
        poll_interval = 600

    def start_and_notify():
        start_worker(account["token"], user_id, username, poll_interval, True)

    import threading
    threading.Thread(target=start_and_notify, daemon=True).start()

    embed = discord.Embed(
        title="✅ Quest Started",
        description=f"Da khoi dong quest cho **`{username}`**",
        color=0x00FF88
    )
    embed.add_field(name="Poll Interval", value=f"{poll_interval} giay", inline=True)
    embed.add_field(name="Auto Accept", value="Enabled ✅", inline=True)
    embed.add_field(name="User ID", value=f"`{user_id[:12]}...`", inline=False)
    embed.set_footer(text="Xem tien do: /queststat")

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="queststat", description="Xem thong ke quest")
async def queststat_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    workers = get_all_workers()
    running_count = len(workers)
    running_list = get_running_accounts()

    stats = database.get_stats()
    recent = stats.get("recent_logs", [])[:10]
    failed = sum(1 for l in recent if l.get("status") == "failed")

    embed = discord.Embed(title="📊 Quest Statistics", color=0x5865F2)
    embed.add_field(name="Tong quest", value=str(stats.get("total_logs", 0)), inline=True)
    embed.add_field(name="Hoan thanh", value=str(stats.get("completed_logs", 0)), inline=True)
    embed.add_field(name="Da nhan", value=str(stats.get("enrolled_logs", 0)), inline=True)
    embed.add_field(name="Active workers", value=str(running_count), inline=True)
    embed.add_field(name="Tai khoan chay", value=str(len(running_list)), inline=True)

    if recent:
        lines = []
        for log_entry in recent[:10]:
            action_icon = action_emoji(log_entry.get("action", ""))
            status_icon = "✅" if log_entry.get("status") == "success" else "❌"
            qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
            lines.append(f"{action_icon} {status_icon} **{qname}**")
        embed.add_field(name="Quest gan day", value="\n".join(lines) or "—", inline=False)
    else:
        embed.add_field(name="Quest gan day", value="—", inline=False)

    embed.set_footer(text=f"Total enrolled: {stats.get('enrolled_logs', 0)} | Failed: {failed}")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="questlist", description="Xem danh sach tai khoan dang chay")
async def questlist_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    workers = get_all_workers()
    running_list = get_running_accounts()
    accounts = database.get_all_accounts()

    if not workers and not accounts:
        embed = discord.Embed(
            title="📋 Quest Accounts",
            description="Chua co tai khoan nao duoc them.",
            color=0xFFAA00
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    embed = discord.Embed(title="📋 Quest Accounts", color=0x5865F2)

    if running_list:
        running_lines = []
        for acc in running_list:
            emoji = account_status_emoji(acc.get("status", "offline"))
            running_lines.append(
                f"{emoji} **{acc.get('username', 'Unknown')}**\n"
                f"   Status: `{acc.get('message', 'N/A')}`"
            )
        embed.add_field(name="🟢 Dang chay", value="\n\n".join(running_lines), inline=False)
    else:
        embed.add_field(name="🟢 Dang chay", value="Khong co tai khoan nao dang chay.", inline=False)

    if accounts:
        offline_lines = []
        for acc in accounts:
            acc_user_id = acc.get("user_id", "")
            if not any(w.get("user_id") == acc_user_id for w in running_list):
                status = acc.get("status", "offline")
                emoji = account_status_emoji(status)
                acc_username = acc.get("username") or acc.get("global_name") or acc_user_id[:12]
                offline_lines.append(f"{emoji} **{acc_username}** - `{status}`")
        
        if offline_lines:
            embed.add_field(name="⚫ Offline", value="\n".join(offline_lines), inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="stopquest", description="Dung auto quest cua mot tai khoan")
@app_commands.describe(user_id="User ID cua tai khoan can dung (de trong = tat ca)")
async def stopquest_command(interaction: discord.Interaction, user_id: str = None):
    await interaction.response.defer(ephemeral=True)

    workers = get_all_workers()

    if user_id:
        filtered = {uid: w for uid, w in workers.items() if uid == user_id}
    else:
        filtered = workers

    if not filtered:
        await interaction.followup.send(
            "⚠️ Khong co tai khoan nao dang chay.",
            ephemeral=True
        )
        return

    stopped = []
    for uid in list(filtered.keys()):
        w = workers.get(uid)
        if w:
            stopped.append(w.username)
        stop_worker(uid)

    embed = discord.Embed(
        title="✅ Da dung",
        description=f"Da dung: **{', '.join(stopped)}**",
        color=0x00FF88
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="helpquest", description="Huong dan su dung quest commands")
async def helpquest_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Quest Commands Help",
        description="Huong dan su dung cac lenh quest",
        color=0x5865F2
    )

    commands_info = [
        ("`/quest <token>`", "Them token va bat dau auto quest. Token lay tu Discord (F12 > Application > Local Storage > token)"),
        ("`/queststat`", "Xem thong ke quest: so luong hoan thanh, loi,..."),
        ("`/questlist`", "Xem danh sach tai khoan dang chay"),
        ("`/stopquest [user_id]`", "Dung auto quest. De trong de dung tat ca."),
        ("`/helpquest`", "Hien thi thong tin nay"),
    ]

    for cmd, desc in commands_info:
        embed.add_field(name=cmd, value=desc, inline=False)

    embed.add_field(
        name="⚠️ Lưu ý",
        value="Token la mat khau cua tai khoan Discord. Khong chia se token voi bat ky ai!",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=False)


# ── Bot Events ────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    log.info(f"✅ Bot online: {bot.user} (ID: {bot.user.id})")
    await tree.sync()
    log.info("🔧 Commands synced")


# ── Run Bot ───────────────────────────────────────────────────────────────────

def run_bot():
    """Run the Discord bot."""
    database.init_db()
    log.info("📦 Database initialized")
    
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        log.error("DISCORD_BOT_TOKEN not set in .env!")
        print("❌ DISCORD_BOT_TOKEN not set in .env!")
        return

    log.info("🚀 Starting quest bot...")
    bot.run(token)


if __name__ == "__main__":
    run_bot()
