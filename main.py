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
        self.party_id = kwargs.pop('party_id', None)  # ✅ must already exist
        self.region = kwargs.pop('region', "EU").upper()  # ✅ enforce uppercase
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
                            logger.error(await response.text())
            except Exception as e:
                logger.error(f"Failed to get netcl (attempt {attempt + 1}): {e}")
                await asyncio.sleep(5 * (attempt + 1))
        return None

    async def client_credentials(self):
        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        payload = {"grant_type": "client_credentials"}
        headers = {"Authorization": f"Basic {LAUNCHER_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=payload, headers=headers) as response:
                logger.info(f"Client credentials: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    self.client_credentials_token = data['access_token']
                    return data
                else:
                    logger.error(await response.text())
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
                logger.info(f"Token creation: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    self.bearer = data['access_token']
                    self.client_id = data['account_id']
                    return data
                else:
                    logger.error(await response.text())
        return None

    async def set_presence(self):
        # ✅ Correct endpoint with namespace "fortnite"
        url = f"https://presence-public-service-prod.ol.epicgames.com/presence/api/v1/fortnite/{self.client_id}/presence"
        headers = {
            "Authorization": f"bearer {self.bearer}",
            "Content-Type": "application/json"
        }
        payload = {
            "status": "Playing",
            "bIsPlaying": True,
            "bIsJoinable": True,
            "bHasVoiceSupport": False,
            "productName": "Fortnite",
            "sessionId": "",
            "properties": {}
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                logger.info(f"Presence update: status {response.status}")
                if response.status != 200:
                    logger.error(await response.text())
    def calculate_checksum(self, ticket_payload, signature):
        if not ticket_payload or not signature:
            logger.error("Cannot calculate checksum: ticket_payload or signature is None")
            return None
        try:
            plaintext = ticket_payload[10:20] + "Don'tMessWithMMS" + signature[2:10]
            data = plaintext.encode('utf-16le')
            sha1_hash = hashlib.sha1(data).digest()
            return sha1_hash[2:10].hex().upper()
        except Exception as e:
            logger.error(f"Failed to calculate checksum: {e}")
            return None

    async def generate_ticket(self):
        if not all([self.client_id, self.netcl, self.party_id, self.bearer, self.link_code, self.playlist, self.region]):
            logger.error("Missing required fields for ticket generation")
            return None, None
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}?partyPlayerIds={self.account_ids}&bucketId={self.netcl}:1:{self.region}:{self.playlist}&player.platform=Windows&player.option.linkCode={self.link_code}&player.option.partyId={self.party_id}"
        headers = {
            "User-Agent": f"Fortnite/{self.build_version} Windows/10",
            "Authorization": f"bearer {self.bearer}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                logger.info(f"Ticket generation: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    return data['payload'], data['signature']
                else:
                    logger.error(await response.text())
                    return None, None

    async def connect_websocket(self, payload, signature, checksum):
        if not all([payload, signature, checksum]):
            return {"status": "error", "message": "Invalid ticket data"}
        headers = {"Authorization": f"Epic-Signed mms-player {payload} {signature} {checksum}"}
        uri = f"wss://fortnite-matchmaking-public-service-live-{self.region}.ol.epicgames.com:443"
        try:
            async with websockets.connect(uri, extra_headers=headers) as ws:
                logger.info("WebSocket connection opened")
                async for message in ws:
                    parsed = ast.literal_eval(message)
                    if parsed.get("name") == "Play":
                        logger.info("Matchmaking process successful")
                        return {"status": "success", "message": f"Custom match started with link code: {self.link_code} (party: {self.party_id})"}
                    else:
                        return {"status": "info", "message": message}
        except Exception as e:
            logger.error(f"Failed to connect websocket: {e}")
            return {"status": "error", "message": str(e)}

    async def check_matchmaking_ban(self):
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}"
        headers = {
            "User-Agent": f"Fortnite/{self.build_version} Windows/10",
            "Authorization": f"bearer {self.bearer}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                logger.info(f"Ban check: status {response.status}")
                data = await response.json()
                return data.get("errorCode") == "errors.com.epicgames.fortnite.player_banned_from_sub_game"

    async def start(self):
        try:
            logger.info("Starting matchmaking process")
            self.token_data = await self.create_token()
            if not self.token_data or not self.bearer:
                return {"status": "error", "message": "Failed to authenticate"}
            await self.client_credentials()
            if not self.client_credentials_token:
                return {"status": "error", "message": "Failed to get client credentials"}
            self.netcl = await self.get_netcl()
            if not self.netcl:
                return {"status": "error", "message": "Failed to fetch netcl"}
            if await self.check_matchmaking_ban():
                return {"status": "error", "message": "The client is currently banned from matchmaking"}
            await self.set_presence()

            if not self.party_id:
                return {"status": "error", "message": "No party_id provided. Join or create a party first."}

            payload, signature = await self.generate_ticket()
            if not payload or not signature:
                return {"status": "error", "message": "Failed to generate matchmaking ticket"}
            checksum = self.calculate_checksum(payload, signature)
            if not checksum:
                return {"status": "error", "message": "Failed to calculate checksum"}
            return await self.connect_websocket(payload, signature, checksum)
        except Exception as e:
            logger.error(f"An error occurred in start: {e}")
            return {"status": "error", "message": str(e)}

# Discord Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")

@bot.command(name='startcustom')
async def start_custom(ctx, link_code=None, party_id=None):
    if link_code is None:
        link_code = os.getenv("LINK_CODE", "abc123")
    if not (6 <= len(link_code) <= 12 and link_code.isalnum()):
        await ctx.send("Error: Link code must be 6-12 alphanumeric characters.")
        return
    if party_id is None:
        party_id = os.getenv("PARTY_ID")
    if not party_id:
        await ctx.send("Error: No party_id provided.")
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
        party_id=party_id,
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
