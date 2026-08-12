import os
import logging

from datetime import datetime

from discord import Activity, ActivityType, Embed, Intents
from discord.ext import commands, tasks
from dotenv import load_dotenv
from mcstatus import JavaServer

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MINECRAFT_SERVER_HOST = os.getenv("MINECRAFT_SERVER_HOST")
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "30"))
STATUS_CHANNEL_ID = os.getenv("STATUS_CHANNEL_ID")
STATUS_MESSAGE_ID_FILE = os.getenv("STATUS_MESSAGE_ID_FILE", ".status_message_id")

logger = logging.getLogger("minecraft_discord_bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

if STATUS_CHANNEL_ID:
    try:
        STATUS_CHANNEL_ID = int(STATUS_CHANNEL_ID)
    except ValueError:
        logger.critical("STATUS_CHANNEL_ID muss eine gültige Zahl sein.")
        raise SystemExit("Fehler: STATUS_CHANNEL_ID ungültig.")

if not DISCORD_BOT_TOKEN:
    logger.critical("DISCORD_BOT_TOKEN ist nicht gesetzt. Bitte .env prüfen.")
    raise SystemExit("Fehler: DISCORD_BOT_TOKEN fehlt.")

if not MINECRAFT_SERVER_HOST:
    logger.critical("MINECRAFT_SERVER_HOST ist nicht gesetzt. Bitte .env prüfen.")
    raise SystemExit("Fehler: MINECRAFT_SERVER_HOST fehlt.")

bot = commands.Bot(command_prefix="!", intents=Intents.default())


def format_activity(status_text: str) -> Activity:
    return Activity(type=ActivityType.playing, name=status_text)


async def fetch_server_status() -> tuple[str, bool, int, int]:
    server = JavaServer.lookup(MINECRAFT_SERVER_HOST)
    try:
        status = server.status()
        online = status.players.online
        maximum = status.players.max
        return f"🟢 Minecraft: {online}/{maximum} Spieler", True, online, maximum
    except Exception as error:
        logger.warning("Server ist offline oder nicht erreichbar: %s", error)
        return "🔴 Minecraft Server offline", False, 0, 0


def load_status_message_id() -> int | None:
    if not os.path.exists(STATUS_MESSAGE_ID_FILE):
        return None
    try:
        with open(STATUS_MESSAGE_ID_FILE, "r", encoding="utf-8") as file:
            return int(file.read().strip())
    except Exception as error:
        logger.warning("Fehler beim Laden der gespeicherten Status-Message-ID: %s", error)
        return None


def save_status_message_id(message_id: int) -> None:
    try:
        with open(STATUS_MESSAGE_ID_FILE, "w", encoding="utf-8") as file:
            file.write(str(message_id))
    except Exception as error:
        logger.error("Fehler beim Speichern der Status-Message-ID: %s", error)


async def create_status_embed(status_text: str, online: bool, online_count: int, max_players: int) -> Embed:
    color = 0x2ECC71 if online else 0xE74C3C
    title = "Minecraft Server Status"
    description = status_text

    embed = Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Server", value=f"`{MINECRAFT_SERVER_HOST}`", inline=False)
    embed.add_field(name="Spieler", value=f"{online_count}/{max_players}", inline=True)
    embed.add_field(name="Status", value="Online" if online else "Offline", inline=True)
    embed.add_field(name="Letzte Prüfung", value=datetime.utcnow().strftime("%d.%m.%Y %H:%M:%S UTC"), inline=False)
    embed.set_footer(text="Aktualisiert alle {} Sekunden".format(CHECK_INTERVAL_SECONDS))
    return embed


async def update_status_message(status_text: str, online: bool, online_count: int, max_players: int) -> None:
    if not STATUS_CHANNEL_ID:
        return

    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if channel is None:
        logger.warning("Status-Kanal mit ID %s nicht gefunden.", STATUS_CHANNEL_ID)
        return

    message_id = load_status_message_id()
    message = None

    if message_id:
        try:
            message = await channel.fetch_message(message_id)
        except Exception as error:
            logger.warning("Status-Nachricht konnte nicht geladen werden: %s", error)
            message = None

    embed = await create_status_embed(status_text, online, online_count, max_players)

    if message is None:
        try:
            message = await channel.send(embed=embed)
            save_status_message_id(message.id)
            logger.info("Neue Status-Nachricht erstellt: %s", message.id)
        except Exception as error:
            logger.error("Fehler beim Senden der Status-Nachricht: %s", error)
        return

    try:
        await message.edit(embed=embed)
        logger.info("Status-Nachricht aktualisiert: %s", status_text)
    except Exception as error:
        logger.error("Fehler beim Aktualisieren der Status-Nachricht: %s", error)


@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def update_bot_presence() -> None:
    status_text, online, online_count, max_players = await fetch_server_status()
    try:
        await bot.change_presence(activity=format_activity(status_text))
        logger.info("Aktualisiere Discord-Status: %s", status_text)
    except Exception as error:
        logger.error("Fehler beim Aktualisieren des Discord-Status: %s", error)

    await update_status_message(status_text, online, online_count, max_players)


@bot.event
async def on_ready() -> None:
    logger.info("Discord-Bot verbunden als %s", bot.user)
    if not update_bot_presence.is_running():
        update_bot_presence.start()
        logger.info("Starte regelmäßige Statusprüfung alle %s Sekunden.", CHECK_INTERVAL_SECONDS)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error("Ein Fehler ist aufgetreten: %s", error)
    await ctx.send("Es ist ein Fehler aufgetreten. Bitte überprüfe die Logs.")


if __name__ == "__main__":
    logger.info("Starte Minecraft-Discord-Bot...")
    bot.run(DISCORD_BOT_TOKEN)
