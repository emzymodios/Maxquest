#!/usr/bin/env python3
"""
Henxi - Discord Quest Auto-Completer Bot
Chỉ chạy Discord bot, không có web dashboard.
"""

import os
import sys
import logging

from dotenv import load_dotenv
load_dotenv()

# Setup logging
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


def print_banner():
    banner = r"""
   ██████╗ ███████╗███████╗██╗   ██╗███╗   ███╗███████╗
  ██╔═══██╗██╔════╝██╔════╝██║   ██║████╗ ████║██╔════╝
  ██║   ██║███████╗███████╗██║   ██║██╔████╔██║█████╗
  ██║   ██║╚════██║╚════██║██║   ██║██║╚██╔╝██║██╔══╝
  ╚██████╔╝███████║███████║╚██████╔╝██║ ╚═╝ ██║███████╗
   ╚═════╝ ╚══════╝╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝
    Discord Quest Auto-Completer — Bot Edition
    """
    print(banner)


def main():
    print_banner()

    # Init database
    import database
    database.init_db()
    log.info("Database initialized: bot_data.db")

    # Check bot token
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not bot_token:
        log.error("❌ DISCORD_BOT_TOKEN not set in .env!")
        print("\n⚠️  Vui long them DISCORD_BOT_TOKEN vao file .env\n")
        print("   Huong dan lay token Discord:")
        print("   1. Mo Discord (F12) > Application > Local Storage > discord.com")
        print("   2. Tim key 'token' va copy value")
        print("   3. Them vao file .env: DISCORD_BOT_TOKEN=your_token_here")
        return

    # Run bot
    log.info("🚀 Starting Discord quest bot...")
    log.info("📡 Commands: /quest, /queststat, /questlist, /stopquest, /helpquest")

    from bot import run_bot
    run_bot()


if __name__ == "__main__":
    main()
