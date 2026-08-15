"""
ONI QUEST - Discord Auto-Completer (Full Control Panel Version)
Tích hợp Dashboard, Điều khiển bằng nút bấm, và Thống kê cá nhân chuẩn xác.
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("oni_quest")

# ── Bot Setup ────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Lưu tạm mapping: token -> thông tin người dùng Discord
token_to_user = {}

# ── Helpers ──────────────────────────────────────────────────────────────────
def action_emoji(action: str) -> str:
    return {"enrolled": "📋", "completed": "✅", "failed": "❌", "pending": "⏳"}.get(action, "❓")

# ── Modal & Views ────────────────────────────────────────────────────────────

class TokenInputModal(discord.ui.Modal, title="Nhập Token Discord"):
    token_input = discord.ui.TextInput(label="TOKEN", placeholder="Dán token Discord của bạn", min_length=50, style=discord.TextStyle.long)
    
    async def on_submit(self, interaction: discord.Interaction):
        token = self.token_input.value.strip()
        try:
            database.add_account(token)
            accounts = database.get_all_accounts()
            account = next((a for a in accounts if a.get("token") == token), None)
            
            user_id = account["user_id"]
            username = account.get("username") or account.get("global_name") or user_id[:12]
            token_to_user[token] = {"discord_user_id": interaction.user.id, "user_id": user_id, "username": username}
            
            await interaction.response.send_message(f"✅ Đã thêm tài khoản: **{username}**", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Lỗi: {e}", ephemeral=True)

class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Nhập Token", style=discord.ButtonStyle.primary, emoji="🔑")
    async def token_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TokenInputModal())

    @discord.ui.button(label="Bắt Đầu", style=discord.ButtonStyle.success, emoji="⚡")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens = [k for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        for token in user_tokens:
            info = token_to_user[token]
            if not get_worker(info["user_id"]):
                start_worker(token, info["user_id"], info["username"], 60, True)
        await interaction.followup.send("⚡ Đã kích hoạt các tài khoản của bạn!", ephemeral=True)

    @discord.ui.button(label="Dừng Quest", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens = [v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id]
        for info in user_tokens:
            stop_worker(info["user_id"])
        await interaction.followup.send("⏹️ Đã dừng các tài khoản của bạn.", ephemeral=True)

    @discord.ui.button(label="Trạng Thái", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens:
            await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
            return

        stats = database.get_stats()
        all_logs = stats.get("recent_logs", [])
        running_accounts = get_running_accounts()
        
        embed = discord.Embed(title="🛡️ ONI QUEST - THỐNG KÊ CÁ NHÂN", color=0x9B59B6)
        
        for token, info in user_tokens.items():
            u_id = info["user_id"]
            is_running = get_worker(u_id) is not None
            
            token_logs = [l for l in all_logs if str(l.get("user_id")) == str(u_id)]
            active_acc = next((acc for acc in running_accounts if str(acc.get("user_id")) == str(u_id)), None)
            
            lines = []
            if active_acc and is_running:
                lines.append(f"🔄 ⏳ **Đang làm**: `{active_acc.get('message', 'Đang xử lý...')}`")
            
            for log_entry in token_logs[:5]:
                act_icon = action_emoji(log_entry.get("action", ""))
                stat_icon = "✅" if log_entry.get("status") == "success" else "❌"
                qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
                lines.append(f"{act_icon} {stat_icon} **{qname}**")
            
            recent_str = "\n".join(lines) if lines else "Chưa có hoạt động quest nào."
            
            field_value = (
                f"🔹 **Trạng Thái**: `{'🟢 Đang chạy' if is_running else '🔴 Đang dừng'}`\n"
                f"📊 **Tổng quest**: `{len(token_logs)}`\n"
                f"📜 **Quest gần đây**:\n{recent_str}"
            )
            embed.add_field(name=f"👤 Tài khoản: {info['username']}", value=field_value, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

# ── Commands ─────────────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="Mở Dashboard ONI QUEST")
async def autoquest(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⚡ **ONI QUEST MANAGER**\nBảng điều khiển hệ thống Auto Quest độc quyền.",
        view=ControlPanelView(), ephemeral=False
    )

@tree.command(name="status", description="Xem thống kê quest cá nhân")
async def status_command(interaction: discord.Interaction):
    # Dùng chung logic với status_btn để đồng bộ
    await ControlPanelView().status_btn(interaction, None)

@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"✅ Bot online: {bot.user}")

if __name__ == "__main__":
    database.init_db()
    bot.run(os.environ.get("DISCORD_BOT_TOKEN"))

