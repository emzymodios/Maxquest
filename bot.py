"""
ONI QUEST - Discord Auto-Completer (Full Control Panel Version)
Tích hợp Dashboard đầy đủ nút bấm, Hướng dẫn và Thống kê cá nhân chuẩn xác.
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
            
            await interaction.response.send_message(f"🛡️ Thêm thành công tài khoản: **{username}**", ephemeral=True)
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
        
        if not user_tokens:
            await interaction.followup.send("❌ Bạn chưa thêm token nào!", ephemeral=True)
            return

        started = []
        for token in user_tokens:
            info = token_to_user[token]
            if not get_worker(info["user_id"]):
                start_worker(token, info["user_id"], info["username"], 60, True)
                started.append(info["username"])
                
        if started:
            await interaction.followup.send(f"⚡ Đã khởi chạy autoquest cho: **{', '.join(started)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Tất cả token của bạn đã chạy rồi!", ephemeral=True)

    @discord.ui.button(label="Dừng Quest", style=discord.ButtonStyle.danger, emoji="⏹️")
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
            await interaction.followup.send(f"⏹️ Đã dừng hệ thống của: **{', '.join(stopped)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có token nào của bạn đang chạy!", ephemeral=True)

    @discord.ui.button(label="Trạng Thái", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens_map = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens_map:
            await interaction.followup.send("❌ Bạn chưa nhập token nào vào hệ thống để thống kê!", ephemeral=True)
            return

        stats = database.get_stats()
        all_logs = stats.get("recent_logs", [])
        running_accounts = get_running_accounts()
        
        embed = discord.Embed(title="🛡️ ONI QUEST - THỐNG KÊ CÁ NHÂN", color=0x9B59B6)
        
        for token, info in user_tokens_map.items():
            u_id = info["user_id"]
            uname = info["username"]
            
            is_running = get_worker(u_id) is not None
            status_text = "🟢 Đang chạy" if is_running else "🔴 Đang dừng"
            
            token_logs = database.get_quest_logs_by_user(u_id, 10)
            total = len(token_logs)
            enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
            failed = sum(1 for l in token_logs if l.get("status") == "failed")
            
            lines = []
            active_acc = next((acc for acc in running_accounts if str(acc.get("user_id")) == str(u_id)), None)
            current_msg = active_acc.get("message") if active_acc else None
            if current_msg and is_running:
                lines.append(f"🔄 ⏳ **Đang làm**: `{current_msg}`")
                
            if token_logs:
                for log_entry in token_logs[:5]:
                    action_icon = action_emoji(log_entry.get("action", ""))
                    status_icon = "✅" if log_entry.get("status") == "success" else "❌"
                    qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
                    lines.append(f"{action_icon} {status_icon} **{qname}**")
            
            recent_str = "\n".join(lines) if lines else "Chưa có hoạt động quest nào."
            
            field_value = (
                f"🔹 **Trạng Thái**: `{status_text}`\n"
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
        embed.add_field(name="🔑 Nhập Token", value="Thêm một hoặc nhiều token Discord của bạn vào hệ thống.", inline=False)
        embed.add_field(name="⚡ Bắt Đầu", value="Kích hoạt tiến trình tự động làm quest.", inline=False)
        embed.add_field(name="⏹️ Dừng Quest", value="Tạm dừng tiến trình đang chạy.", inline=False)
        embed.add_field(name="📊 Trạng Thái", value="Xem thống kê chi tiết từng tài khoản kèm quest gần đây.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

# ── Commands ─────────────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="⚡ ONI QUEST Control Panel - All-in-One")
async def autoquest(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚡ ONI QUEST MANAGER",
        description="Bảng điều khiển hệ thống Auto Quest độc quyền",
        color=0x9B59B6
    )
    embed.add_field(name="🛡️ Trạng thái hệ thống", value="`🟢 Sẵn sàng hoạt động`", inline=False)
    embed.add_field(name="⚙️ Thao tác nhanh", value="Sử dụng các nút bên dưới để cấu hình và điều khiển bot.", inline=False)
    
    await interaction.response.send_message(embed=embed, view=ControlPanelView(), ephemeral=False)

@tree.command(name="status", description="Xem thống kê quest cá nhân theo token đã nhập")
async def status_command(interaction: discord.Interaction):
    await ControlPanelView().status_btn(interaction, None)

@bot.event
async def on_ready():
    await tree.sync()
    log.info(f"✅ Bot online: {bot.user}")

# ── Hàm chạy bot tương thích với main.py ─────────────────────────────────────
def run_bot():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if token:
        bot.run(token)
    else:
        log.error("DISCORD_BOT_TOKEN không được tìm thấy cho bot!")

