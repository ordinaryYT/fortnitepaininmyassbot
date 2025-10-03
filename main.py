import os
import aiohttp
import asyncio
import logging
import discord
from discord.ext import commands
from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fortnite-bot")

# === ENV VARS ===
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ACCOUNT_ID    = os.getenv("ACCOUNT_ID")
DEVICE_ID     = os.getenv("DEVICE_ID")
SECRET        = os.getenv("SECRET")
LINK_CODE     = os.getenv("LINK_CODE")
PARTY_ID      = os.getenv("PARTY_ID")
PLAYLIST      = os.getenv("PLAYLIST", "playlist_defaultsolo")
REGION        = os.getenv("REGION", "EU")
PORT          = int(os.getenv("PORT", 10000))  # Render expects this

# Fortnite client base64 (always the same)
CLIENT_AUTH = "ZWM2ODRiOGM2ODdmNDc5ZmFkZWEzY2IyYWQ4M2Y1YzY6ZTFmMzFjMjExZjI4NDEzMTg2MjYyZDM3ZjlmNmY5YzY="

OAUTH_URL = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
MMS_URL   = "https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice"

# Discord bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

class FortniteClient:
    def __init__(self):
        self.access_token = None
        self.client = None
        self.ticket_info = None

    async def init(self):
        self.client = aiohttp.ClientSession()

    async def create_token(self):
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"basic {CLIENT_AUTH}"
        }
        data = {
            "grant_type": "device_auth",
            "account_id": ACCOUNT_ID,
            "device_id": DEVICE_ID,
            "secret": SECRET
        }
        async with self.client.post(OAUTH_URL, headers=headers, data=data) as resp:
            text = await resp.text()
            if resp.status == 200:
                body = await resp.json()
                self.access_token = body["access_token"]
                logger.info("✅ Got bearer token")
            else:
                logger.error(f"❌ Token creation failed {resp.status}: {text}")
                raise Exception("Token error")

    async def request_ticket(self):
        headers = {
            "Authorization": f"bearer {self.access_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        bucket_id = f"45716758:1:{REGION}:{PLAYLIST}"
        params = {
            "partyPlayerIds": ACCOUNT_ID,
            "bucketId": bucket_id,
            "player.platform": "Windows",
            "player.option.customKey": LINK_CODE,
            "player.option.partyId": PARTY_ID,
            "player.input": "KBM",
            "player.option.uiLanguage": "en"
        }
        url = f"{MMS_URL}/ticket/player/{ACCOUNT_ID}"
        async with self.client.post(url, headers=headers, params=params) as resp:
            text = await resp.text()
            if resp.status == 200:
                self.ticket_info = await resp.json()
                logger.info("✅ Ticket requested")
                return self.ticket_info
            else:
                logger.error(f"❌ Ticket request failed {resp.status}: {text}")
                raise Exception("Ticket error")

    async def start_match(self):
        if not self.ticket_info:
            raise Exception("No ticket available, run !startcustom first")

        headers = {
            "Authorization": f"bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        url = f"{MMS_URL}/ticket/player/{ACCOUNT_ID}/play"
        async with self.client.post(url, headers=headers) as resp:
            text = await resp.text()
            if resp.status == 200:
                logger.info("🚀 Match started")
                return await resp.json()
            else:
                logger.error(f"❌ Failed to start match {resp.status}: {text}")
                raise Exception("Start error")

    async def close(self):
        if self.client:
            await self.client.close()

fortnite = FortniteClient()

# === Discord Events & Commands ===
@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")

@bot.command(name="startcustom")
async def start_custom(ctx):
    try:
        await fortnite.create_token()
        await fortnite.request_ticket()
        await ctx.send(f"✅ Custom key `{LINK_CODE}` queued in `{PLAYLIST}` ({REGION}). Use `!start` to launch.")
    except Exception as e:
        await ctx.send(f"❌ Failed: {e}")

@bot.command(name="start")
async def start(ctx):
    try:
        await fortnite.start_match()
        await ctx.send("🚀 Custom match started!")
    except Exception as e:
        await ctx.send(f"❌ Failed to start: {e}")

# === Healthcheck server for Render ===
async def handle(request):
    return web.Response(text="Fortnite bot running!")

async def start_servers():
    await fortnite.init()

    # Start aiohttp webserver on Render's PORT
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ Web server running on port {PORT}")

    # Start Discord bot
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(start_servers())
    except KeyboardInterrupt:
        asyncio.run(fortnite.close())
