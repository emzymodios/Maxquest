"""
ONI QUEST - Discord Auto-Completer
Pure Discord Bot (No Web Panel)
"""

import os
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
            
            if not account:
                await interaction.response.send_message(f"❌ Không thể thêm account!", ephemeral=True)
                return
            
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
                    f"⚠️ Tài khoản **{username}** đã chạy rồi!",
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

@tree.command(name="autoquest", description="🔑 Quest Auto-Completer Control Panel")
async def autoquest(interaction: discord.Interaction):
    """Hiển thị embed + GIF + buttons"""
    embed = discord.Embed(
        title="🔑 QUEST AUTO-COMPLETER",
        description="Chào mừng đến với Quest Auto-Completer!\nNhấn nút bên dưới để quản lý quest của bạn.",
        color=0x9B59B6
    )
    
    # Thêm ảnh GIF
    embed.set_image(url="https://media.giphy.com/media/WJmwuUXuLvaSJo9owu/giphy.gif")
    
    # Thêm features
    embed.add_field(name="🔑 Auto Quest", value="Bắt đầu hoàn thành quest tự động", inline=False)
    embed.add_field(name="💎 Thống kê Quest", value="Xem Quest đã làm, chưa làm, Orbs đã nhận và chưa nhận", inline=False)
    embed.add_field(name="⏹ Stop Quest", value="Dừng phiên hiện tại", inline=False)
    embed.add_field(name="📝 Mô tả", value="Token chỉ dùng để hoàn thành quest, không lưu trữ.", inline=False)
    embed.set_footer(text="By: Oni • Quest Auto-Completer")
    
    await interaction.response.send_message(embed=embed, view=ControlPanelView(), ephemeral=False)

@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"✅ Bot online: {bot.user}")

# ── Run Bot ──────────────────────────────────────────────────────────────────

def run_bot():
    """Run Discord Bot"""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        log.error("❌ DISCORD_BOT_TOKEN không được tìm thấy!")

if __name__ == "__main__":
    run_bot()
