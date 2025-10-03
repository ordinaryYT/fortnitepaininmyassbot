import aiohttp
from aiohttp.web import Application
import websockets
import hashlib
import json
import ast
import asyncio
import os
import discord
from discord.ext import commands
import logging

# Configure logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')  # Save logs to file for Render
    ]
)
logger = logging.getLogger(__name__)

ANDROID_TOKEN = "M2Y2OWU1NmM3NjQ5NDkyYzhjYzI5ZjFhZjA4YThhMTI6YjUxZWU5Y2IxMjIzNGY1MGE2OWVmYTY3ZWY1MzgxMmU="
LAUNCHER_TOKEN = "MzRhMDJjZjhmNDQxNGUyOWIxNTkyMTg3NmRhMzZmOWE6ZGFhZmJjY2M3Mzc3NDUwMzlkZmZlNTNkOTRmYzc2Y2Y="

class DontMessWithMMS:
    def __init__(self, **kwargs):
        self.account_ids = ",".join(kwargs.pop('account_ids', []))
        self.exchange_code = kwargs.pop('exchange_code', None)
        self.playlist = kwargs.pop('playlist', None)
        self.party_id = kwargs.pop('party_id', None)
        self.region = kwargs.pop('region', "EU").lower()
        self.fill = "true" if kwargs.pop('fill', None) else "false"
        self.client_id = kwargs.pop('client_id', None)
        self.bearer = kwargs.pop('bearer', None)
        self.client_credentials_token = kwargs.pop('client_credentials_token', None)
        self.token_data = kwargs.pop('token_data', None)
        self.netcl = kwargs.pop('netcl', None)
        self.device_id = kwargs.pop('device_id', None)
        self.secret = kwargs.pop('secret', None)
        self.link_code = kwargs.pop('link_code', None)
        self.build_version = "37.30"  # Hardcoded for 2025 stability

    async def get_netcl(self):
        url = "https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/matchmaking/session/matchMakingRequest"
        payload = {"criteria": [], "openPlayersRequired": 1, "buildUniqueId": "", "maxResults": 1}
        headers = {"Authorization": f"bearer {self.bearer}", "Content-Type": "application/json"}
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        logger.info(f"Netcl fetch attempt {attempt + 1}: status {response.status}")
                        if response.status == 200:
                            data = await response.json()
                            self.netcl = data[0]["buildUniqueId"]
                            logger.info(f"Fetched netcl: {self.netcl}")
                            return self.netcl
                        else:
                            error_text = await response.text()
                            logger.error(f"Netcl fetch failed: {response.status} - {error_text}")
                            if response.status == 429:
                                await asyncio.sleep(5 * (attempt + 1))
                            else:
                                break
            except Exception as e:
                logger.error(f"Failed to get netcl (attempt {attempt + 1}): {e}")
                await asyncio.sleep(5 * (attempt + 1))
        return None
    async def client_credentials(self):
        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        payload = {"grant_type": "client_credentials"}
        headers = {"Authorization": f"Basic {LAUNCHER_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=payload, headers=headers) as response:
                        logger.info(f"Client credentials attempt {attempt + 1}: status {response.status}")
                        if response.status == 200:
                            data = await response.json()
                            self.client_credentials_token = data['access_token']
                            logger.info("Fetched client credentials token")
                            return data
                        else:
                            logger.error(await response.text())
            except Exception as e:
                logger.error(f"Failed to get client credentials (attempt {attempt + 1}): {e}")
        return None

    async def create_token(self):
        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        payload = {
            "grant_type": "device_auth",
            "account_id": self.client_id,
            "device_id": self.device_id,
            "secret": self.secret
        }
        headers = {"Authorization": f"Basic {ANDROID_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, headers=headers) as response:
                logger.info(f"Token creation attempt: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    self.bearer = data['access_token']
                    self.client_id = data['account_id']
                    logger.info("Fetched bearer token")
                    return data
                else:
                    logger.error(await response.text())
        return None

    async def create_party(self):
        endpoint = "https://party-service-prod.ol.epicgames.com/party/api/v1/Fortnite/parties"
        payload = {
            "config": {
                "join_confirmation": False,
                "joinability": "OPEN",
                "max_size": 16,
                "chat_enabled": True,
                "discoverability": "ALL",
                "sub_type": "default",
                "type": "DEFAULT",
                "invite_ttl_seconds": 14400,
                "join_in_progress_enabled": True
            },
            "members": [
                {
                    "account_id": self.client_id,
                    "meta": {
                        "urn:epic:member:dn_s": self.client_id,
                        "urn:epic:member:platform_s": "WIN",
                        "urn:epic:member:platform_version_s": f"++Fortnite+Release-{self.build_version}",
                        "urn:epic:member:build_s": f"{self.build_version}-CL-1234567"
                    },
                    "role": "CAPTAIN",
                    "revision": 0,
                    "connection": {
                        "id": self.client_id,
                        "connected_at": "2025-10-03T00:00:00.000Z",
                        "meta": {
                            "urn:epic:conn:platform_s": "WIN",
                            "urn:epic:conn:build_s": f"{self.build_version}-CL-1234567"
                        }
                    }
                }
            ],
            "meta": {
                "urn:epic:cfg:build-id_s": f"{self.build_version}-CL-1234567",
                "urn:epic:cfg:privacy_s": "PUBLIC"
            }
        }
        headers = {
            "Authorization": f"bearer {self.bearer}",
            "Content-Type": "application/json",
            "User-Agent": f"Fortnite/{self.build_version} Windows/10",
            "X-Epic-Device-ID": self.device_id
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, json=payload, headers=headers) as response:
                logger.info(f"Party creation attempt: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    self.party_id = data['id']
                    logger.info(f"Created new party ID: {self.party_id}")
                    return self.party_id
                else:
                    logger.error(await response.text())
        return None

    # (rest of the class unchanged: calculate_checksum, generate_ticket, connect_websocket, etc.)

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")

@bot.command(name='startcustom')
async def start_custom(ctx, link_code=None):
    if link_code is None:
        link_code = os.getenv("LINK_CODE", "abc123")
    if not (6 <= len(link_code) <= 12 and link_code.isalnum()):
        await ctx.send("Error: Link code must be 6-12 alphanumeric characters.")
        return
    playlist = os.getenv("PLAYLIST", "Playlist_DefaultSolo")
    mms = DontMessWithMMS(
        account_ids=["ced24960d641410390aef731202c0ae2"],
        client_id="ced24960d641410390aef731202c0ae2",
        device_id="87fd14d15b954a839a9e474b8fed3eb3",
        secret=os.getenv("SECRET"),
        playlist=playlist,
        link_code=link_code,
        region=os.getenv("REGION", "EU"),
        fill=False
    )
    result = await mms.start()
    await ctx.send(f"Custom match status: {result['message']}")

# Web Server
async def health_check(request):
    return aiohttp.web.json_response({"status": "ok"})

app = Application()
app.router.add_get('/health', health_check)

async def start_web_and_bot():
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000)))
    await site.start()
    await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(start_web_and_bot())
