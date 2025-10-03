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
                            error_text = await response.text()
                            logger.error(f"Client credentials failed: {response.status} - {error_text}")
                            if response.status == 429:
                                await asyncio.sleep(5 * (attempt + 1))
                            else:
                                break
            except Exception as e:
                logger.error(f"Failed to get client credentials (attempt {attempt + 1}): {e}")
                await asyncio.sleep(5 * (attempt + 1))
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
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=payload, headers=headers) as response:
                        logger.info(f"Token creation attempt {attempt + 1}: status {response.status}")
                        if response.status == 200:
                            data = await response.json()
                            self.bearer = data['access_token']
                            self.client_id = data['account_id']
                            logger.info("Fetched bearer token")
                            return data
                        else:
                            error_text = await response.text()
                            logger.error(f"Token creation failed: {response.status} - {error_text}")
                            if response.status == 429:
                                await asyncio.sleep(5 * (attempt + 1))
                            else:
                                break
            except Exception as e:
                logger.error(f"Failed to get access token (attempt {attempt + 1}): {e}")
                await asyncio.sleep(5 * (attempt + 1))
        return None

    async def create_party(self):
        endpoints = [
            "https://party-service-prod.ol.epicgames.com/party/api/v1/parties",
            "https://party-service-prod02.ol.epicgames.com/party/api/v1/parties"
        ]
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
            "User-Agent": f"Fortnite/37.30 Windows/10"
        }
        for endpoint in endpoints:
            for attempt in range(3):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(endpoint, json=payload, headers=headers) as response:
                            logger.info(f"Party creation attempt {attempt + 1} at {endpoint}: status {response.status}")
                            if response.status == 200:
                                data = await response.json()
                                self.party_id = data['id']
                                logger.info(f"Created new party ID: {self.party_id} (build: {self.build_version})")
                                return self.party_id
                            else:
                                error_text = await response.text()
                                logger.error(f"Party creation failed at {endpoint}: {response.status} - {error_text}")
                                if response.status == 429:
                                    await asyncio.sleep(5 * (attempt + 1))
                                else:
                                    break
                except Exception as e:
                    logger.error(f"Failed to create party at {endpoint} (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(5 * (attempt + 1))
        logger.error("All party creation endpoints failed")
        return None

    def calculate_checksum(self, ticket_payload, signature):
        if not ticket_payload or not signature:
            logger.error("Cannot calculate checksum: ticket_payload or signature is None")
            return None
        try:
            plaintext = ticket_payload[10:20] + "Don'tMessWithMMS" + signature[2:10]
            data = plaintext.encode('utf-16le')
            sha1_hash = hashlib.sha1(data).digest()
            checksum = sha1_hash[2:10].hex().upper()
            return checksum
        except Exception as e:
            logger.error(f"Failed to calculate checksum: {e}")
            return None

    async def generate_ticket(self):
        if not all([self.client_id, self.netcl, self.party_id, self.bearer, self.link_code, self.playlist, self.region]):
            missing = [k for k, v in {"client_id": self.client_id, "netcl": self.netcl, "party_id": self.party_id, "bearer": self.bearer, "link_code": self.link_code, "playlist": self.playlist, "region": self.region}.items() if not v]
            logger.error(f"Cannot generate ticket: missing fields {missing}")
            return None, None
        try:
            url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}?partyPlayerIds={self.account_ids}&bucketId={self.netcl}:1:{self.region}:{self.playlist}&player.platform=Windows&player.subregions=DE,GB,FR&player.option.linkCode={self.link_code}&player.option.fillTeam={self.fill}&player.option.preserveSquad=false&player.option.crossplayOptOut=false&player.option.partyId={self.party_id}&player.option.splitScreen=false&party.WIN=true&input.KBM=true&player.input=KBM&player.option.microphoneEnabled=true&player.option.uiLanguage=en"
            headers = {
                "User-Agent": f"Fortnite/37.30 Windows/10",
                "Authorization": f"bearer {self.bearer}"
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    logger.info(f"Ticket generation attempt: status {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        payload = data['payload']
                        signature = data['signature']
                        logger.info("Generated matchmaking ticket")
                        return payload, signature
                    else:
                        error_text = await response.text()
                        logger.error(f"Ticket generation failed: {response.status} - {error_text}")
                        return None, None
        except Exception as e:
            logger.error(f"Failed to generate ticket: {e}")
            return None, None

    async def connect_websocket(self, payload, signature, checksum):
        if not all([payload, signature, checksum]):
            logger.error(f"Cannot connect WebSocket: invalid inputs (payload: {payload}, signature: {signature}, checksum: {checksum})")
            return {"status": "error", "message": "Invalid ticket data"}
        headers = {"Authorization": f"Epic-Signed mms-player {payload} {signature} {checksum}"}
        uri = f"wss://fortnite-matchmaking-public-service-live-{self.region}.ol.epicgames.com:443"
        try:
            async with websockets.connect(uri, extra_headers=headers) as ws:
                logger.info("WebSocket connection opened")
                async for message in ws:
                    parsed = ast.literal_eval(message)
                    if parsed["name"] == "Play":
                        logger.info("Matchmaking process successful")
                        return {"status": "success", "message": f"Custom match started with link code: {self.link_code} (party: {self.party_id})"}
                    else:
                        logger.info(f"WebSocket message: {message}")
                        return {"status": "info", "message": message}
        except Exception as e:
            logger.error(f"Failed to connect websocket: {e}")
            return {"status": "error", "message": str(e)}

    async def check_matchmaking_ban(self):
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}"
        headers = {
            "User-Agent": f"Fortnite/37.30 Windows/10",
            "Authorization": f"bearer {self.bearer}"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    logger.info(f"Ban check: status {response.status}")
                    data = await response.json()
                    return data.get("errorCode", None) == "errors.com.epicgames.fortnite.player_banned_from_sub_game"
        except Exception as e:
            logger.error(f"Failed to check ban status: {e}")
            return False

    async def start(self):
        try:
            logger.info("Starting matchmaking process")
            self.token_data = await self.create_token()
            if not self.token_data or not self.bearer:
                logger.error("Failed to authenticate")
                return {"status": "error", "message": "Failed to authenticate"}
            await self.client_credentials()
            if not self.client_credentials_token:
                logger.error("Failed to get client credentials")
                return {"status": "error", "message": "Failed to get client credentials"}
            self.netcl = await self.get_netcl()
            if not self.netcl:
                logger.error("Failed to fetch netcl")
                return {"status": "error", "message": "Failed to fetch netcl"}
            is_banned = await self.check_matchmaking_ban()
            if is_banned:
                logger.error("Client is banned from matchmaking")
                return {"status": "error", "message": "The client is currently banned from matchmaking"}
            self.party_id = await self.create_party()
            if not self.party_id:
                logger.error("Failed to create party")
                return {"status": "error", "message": "Failed to create party"}
            payload, signature = await self.generate_ticket()
            if not payload or not signature:
                logger.error("Failed to generate matchmaking ticket")
                return {"status": "error", "message": "Failed to generate matchmaking ticket"}
            checksum = self.calculate_checksum(payload, signature)
            if not checksum:
                logger.error("Failed to calculate checksum")
                return {"status": "error", "message": "Failed to calculate checksum"}
            return await self.connect_websocket(payload, signature, checksum)
        except Exception as e:
            logger.error(f"An error occurred in start: {e}")
            return {"status": "error", "message": f"Failed to start matchmaking: {str(e)}"}

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
        logger.error(f"Invalid link code: {link_code}")
        await ctx.send("Error: Link code must be 6-12 alphanumeric characters.")
        return
    playlist = os.getenv("PLAYLIST", "Playlist_DefaultSolo")
    logger.info(f"Starting custom match with link code: {link_code}, playlist: {playlist}")
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
    logger.info(f"Custom match result: {result['message']}")
    await ctx.send(f"Custom match status: {result['message']}")

# Web Server to Keep Render Happy
async def health_check(request):
    logger.info("Health check requested")
    return aiohttp.web.json_response({"status": "ok"})

app = Application()
app.router.add_get('/health', health_check)

async def start_web_and_bot():
    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000)))
    await site.start()
    logger.info("Web server started")
    await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    logger.info("Starting application")
    asyncio.run(start_web_and_bot())
