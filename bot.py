"""
ONI QUEST - Discord Auto-Completer
Pure Discord Bot (No Web Panel)
Full Features Version
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
            
            if not account:
                await interaction.response.send_message(f"❌ Không thể thêm account!", ephemeral=True)
                return
            
            user_id = account["user_id"]
            username = account.get("username") or account.get("global_name") or user_id[:12]
            token_to_user[token] = {"discord_user_id": interaction.user.id, "user_id": user_id, "username": username}
            
            # Tự động bắt đầu làm quest
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

class AccountSelectView(discord.ui.View):
    def __init__(self, user_tokens_map: dict, interaction: discord.Interaction):
        super().__init__()
        self.user_tokens_map = user_tokens_map
        self.interaction = interaction
        
        # Tạo select menu với tất cả nick
        select = discord.ui.Select(
            placeholder="Chọn tài khoản để xem stats",
            options=[
                discord.SelectOption(label=info["username"], value=token)
                for token, info in user_tokens_map.items()
            ]
        )
        select.callback = self.on_select
        self.add_item(select)
    
    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_token = interaction.data["values"][0]
        await self.show_account_stats(interaction, selected_token)
    
    async def show_account_stats(self, interaction: discord.Interaction, token: str):
        """Hiển thị stats của 1 tài khoản"""
        info = self.user_tokens_map[token]
        u_id = info["user_id"]
        uname = info["username"]
        
        running_accounts = get_running_accounts()
        
        embed = discord.Embed(title="🔮 ONI QUEST - STATUS", color=0x9B59B6)
        
        is_running = get_worker(u_id) is not None
        status_text = "🟢 Đang chạy" if is_running else "🔴 Đang dừng"
        
        token_logs = database.get_quest_logs_by_user(u_id, 10)
        total = len(token_logs)
        enrolled = sum(1 for l in token_logs if l.get("action") == "enrolled")
        failed = sum(1 for l in token_logs if l.get("status") == "failed")
        completed = sum(1 for l in token_logs if l.get("status") == "success")
        
        lines = []
        active_acc = next((acc for acc in running_accounts if str(acc.get("user_id")) == str(u_id)), None)
        current_msg = active_acc.get("message") if active_acc else None
        if current_msg and is_running:
            lines.append(f"⚔️🥇 **Đang làm**: `{current_msg}`")
            
        if token_logs:
            for log_entry in token_logs[:5]:
                action_icon = action_emoji(log_entry.get("action", ""))
                status_icon = "✅" if log_entry.get("status") == "success" else "❌"
                qname = log_entry.get("quest_name") or f"Quest#{log_entry.get('quest_id', '?')}"
                lines.append(f"{action_icon} {status_icon} **{qname}**")
        
        recent_str = "\n".join(lines) if lines else "Chưa có hoạt động quest nào."
        
        field_value = (
            f"💠 **Trạng Thái**: {status_text}\n"
            f"📊 **Tổng quest**: `{total}`\n"
            f"🌱 **Đã nhận**: `{enrolled}`\n"
            f"❌ **Thất bại**: `{failed}`\n"
            f"📜 **Quest gần đây**:\n{recent_str}"
        )
        embed.add_field(name=f"👤 {uname}", value=field_value, inline=False)
        
        embed.set_footer(text="⚡ ONI QUEST SYSTEM • High Performance Auto-Completer")
        await interaction.followup.send(embed=embed, ephemeral=True)

class ControlPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Auto Quest", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def auto_quest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TokenInputModal())

    @discord.ui.button(label="Status", style=discord.ButtonStyle.success, emoji="🔮")
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens_map = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens_map:
            await interaction.followup.send("❌ Bạn chưa nhập token nào!", ephemeral=True)
            return
        
        # Nếu chỉ có 1 token, hiển thị stats ngay
        if len(user_tokens_map) == 1:
            token = list(user_tokens_map.keys())[0]
            select_view = AccountSelectView(user_tokens_map, interaction)
            await select_view.show_account_stats(interaction, token)
        else:
            # Nếu > 1 token, hiển thị select menu
            select_view = AccountSelectView(user_tokens_map, interaction)
            await interaction.followup.send("Chọn tài khoản:", view=select_view, ephemeral=True)

    @discord.ui.button(label="Stop Quest", style=discord.ButtonStyle.danger, emoji="❌")
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
            await interaction.followup.send(f"❌ Đã dừng: **{', '.join(stopped)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có quest nào đang chạy!", ephemeral=True)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, emoji="🔄")
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user_tokens_map = {k: v for k, v in token_to_user.items() if v["discord_user_id"] == interaction.user.id}
        
        if not user_tokens_map:
            await interaction.followup.send("❌ Bạn chưa nhập token nào!", ephemeral=True)
            return

        restarted = []
        for token, info in user_tokens_map.items():
            u_id = info["user_id"]
            uname = info["username"]
            
            # Dừng worker cũ nếu đang chạy
            if get_worker(u_id):
                stop_worker(u_id)
            
            # Khởi động lại worker
            start_worker(token, u_id, uname, 60, True)
            restarted.append(uname)
        
        if restarted:
            await interaction.followup.send(f"🔄 Đã restart thành công: **{', '.join(restarted)}**", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Không có token nào để restart!", ephemeral=True)

# ── Discord Commands ─────────────────────────────────────────────────────────

@tree.command(name="autoquest", description="⛩️ Oni Auto Quest Control Panel")
async def autoquest(interaction: discord.Interaction):
    """Hiển thị embed + GIF + buttons"""
    embed = discord.Embed(
        title="⛩️𝐎𝐍𝐈 • 𝐀𝐔𝐓𝐎 𝐐𝐔𝐄𝐒𝐓",
        description="*🌙 Welcome to Oni Auto Quest ✨*",
        color=0x9B59B6
    )
    
    # Thêm thumbnail GIF ở trên phải (nhỏ)
    embed.set_thumbnail(url="https://media.giphy.com/media/pwGIVFqY2SwWDuuNW2/giphy.gif")
    
    # Thêm ảnh GIF sau welcome (to)
    embed.set_image(url="https://media.giphy.com/media/WJmwuUXuLvaSJo9owu/giphy.gif")
    
    # Thêm features
    embed.add_field(name="⚔️ Auto Quest", value="Nhập token Discord - Tự động khởi chạy làm quest", inline=False)
    embed.add_field(name="🔮 Status", value="Xem chi tiết quest làm được, quest đang làm, trạng thái từng tài khoản", inline=False)
    embed.add_field(name="❌ Stop Quest", value="Dừng phiên làm quest hiện tại", inline=False)
    embed.add_field(name="🔄 Restart", value="Khởi động lại tất cả account đã nhập token", inline=False)
    
    embed.set_footer(text="ᵐᵃᵈᵉ ᵇʸ ᴼɴɪ")
    
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

