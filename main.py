import os
import threading
import logging

from dotenv import load_dotenv
from flask import Flask

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("henxi")

app = Flask(__name__)


@app.get("/")
def home():
    return "Discord bot is running"


@app.get("/health")
def health():
    return {"status": "ok"}


def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def main():
    import database

    database.init_db()
    log.info("Database initialized")

    bot_token = os.environ.get("DISCORD_BOT_TOKEN")

    if not bot_token:
        log.error("DISCORD_BOT_TOKEN is not set")
        return

    threading.Thread(target=run_web, daemon=True).start()
    log.info("HTTP server started")

    from bot import run_bot
    run_bot()


if __name__ == "__main__":
    main()
