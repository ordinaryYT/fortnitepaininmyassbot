# Part 1/2
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
from urllib.parse import quote_plus

# Configure logging for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

ANDROID_TOKEN = "M2Y2OWU1NmM3NjQ5NDkyYzhjYzI5ZjFhZjA4YThhMTI6YjUxZWU5Y2IxMjIzNGY1MGE2OWVmYTY3ZWY1MzgxMmU="
LAUNCHER_TOKEN = "MzRhMDJjZjhmNDQxNGUyOWIxNTkyMTg3NmRhMzZmOWE6ZGFhZmJjY2M3Mzc3NDUwMzlkZmZlNTNkOTRmYzc2Y2Y="

class DontMessWithMMS:
    def __init__(self, **kwargs):
        # account_ids can be list; store as comma-separated string
        self.account_ids = ",".join(kwargs.pop('account_ids', []))
        self.exchange_code = kwargs.pop('exchange_code', None)
        self.playlist = kwargs.pop('playlist', None)
        # party_id must already exist (you manage party creation externally)
        self.party_id = kwargs.pop('party_id', None)
        # region should be uppercase (Epic expects e.g. "EU")
        self.region = kwargs.pop('region', "EU").upper()
        self.fill = "true" if kwargs.pop('fill', None) else "false"
        self.client_id = kwargs.pop('client_id', None)
        self.bearer = kwargs.pop('bearer', None)
        self.client_credentials_token = kwargs.pop('client_credentials_token', None)
        self.token_data = kwargs.pop('token_data', None)
        self.netcl = kwargs.pop('netcl', None)
        self.device_id = kwargs.pop('device_id', None)
        self.secret = kwargs.pop('secret', None)
        self.link_code = kwargs.pop('link_code', None)
        self.build_version = "37.30"

    async def get_netcl(self):
        url = "https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/matchmaking/session/matchMakingRequest"
        payload = {"criteria": [], "openPlayersRequired": 1, "buildUniqueId": "", "maxResults": 1}
        headers = {"Authorization": f"bearer {self.bearer}", "Content-Type": "application/json"}
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        logger.info(f"Netcl fetch attempt {attempt + 1}: status {response.status}")
                        text = await response.text()
                        if response.status == 200:
                            data = await response.json()
                            # defensive: ensure index exists
                            if isinstance(data, list) and len(data) > 0 and "buildUniqueId" in data[0]:
                                self.netcl = data[0]["buildUniqueId"]
                                logger.info(f"Fetched netcl: {self.netcl}")
                                return self.netcl
                            else:
                                logger.error("Unexpected netcl payload: " + text)
                        else:
                            logger.error("Netcl error body: " + text)
                            if response.status == 429:
                                await asyncio.sleep(5 * (attempt + 1))
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
                text = await response.text()
                if response.status == 200:
                    data = await response.json()
                    self.client_credentials_token = data.get('access_token')
                    logger.info("Fetched client credentials token")
                    return data
                else:
                    logger.error("Client credentials error body: " + text)
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
                text = await response.text()
                if response.status == 200:
                    data = await response.json()
                    self.bearer = data.get('access_token')
                    self.client_id = data.get('account_id', self.client_id)
                    logger.info("Fetched bearer token")
                    return data
                else:
                    logger.error("Token creation error body: " + text)
        return None

    async def set_presence(self):
        # Try two presence endpoints: namespaced 'fortnite' first, then '_' fallback.
        candidates = [
            f"https://presence-public-service-prod.ol.epicgames.com/presence/api/v1/fortnite/{self.client_id}/presence",
            f"https://presence-public-service-prod.ol.epicgames.com/presence/api/v1/_/{self.client_id}/presence"
        ]
        headers = {"Authorization": f"bearer {self.bearer}", "Content-Type": "application/json"}
        payload = {
            "status": "Playing",
            "bIsPlaying": True,
            "bIsJoinable": True,
            "bHasVoiceSupport": False,
            "productName": "Fortnite",
            "sessionId": "",
            "properties": {}
        }
        for url in candidates:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        text = await response.text()
                        logger.info(f"Presence update attempt at {url} -> status {response.status}")
                        if response.status in (200, 204):
                            logger.info("Presence set successfully")
                            return True
                        else:
                            # log body and try next endpoint
                            logger.error(f"Presence endpoint {url} returned {response.status}: {text}")
            except Exception as e:
                logger.error(f"Presence request to {url} failed: {e}")
        # if we get here, both presence attempts failed
        return False

    async def create_party(self):
        # intentionally kept for completeness but you said you'll create the party externally;
        # we will no longer call this from start() if party_id is provided.
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
                    "revision": 0
                }
            ],
            "join_info": {
                "connection": {
                    "id": self.client_id,
                    "meta": {
                        "urn:epic:conn:platform_s": "WIN",
                        "urn:epic:conn:type_s": "game",
                        "urn:epic:conn:build_s": f"{self.build_version}-CL-1234567"
                    }
                },
                "meta": {
                    "urn:epic:member:platform_s": "WIN"
                }
            },
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
                text = await response.text()
                logger.info(f"Party creation: status {response.status}")
                if response.status in (200, 201):
                    data = await response.json()
                    self.party_id = data.get('id', self.party_id)
                    logger.info(f"Created/updated party id: {self.party_id}")
                    return self.party_id
                else:
                    logger.error("Party creation error body: " + text)
        return None
# Part 2/2 (rest of file)
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
        # Defensive checks
        required = {
            "client_id": self.client_id,
            "netcl": self.netcl,
            "party_id": self.party_id,
            "bearer": self.bearer,
            "link_code": self.link_code,
            "playlist": self.playlist,
            "region": self.region
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            logger.error("Cannot generate ticket: missing fields " + ", ".join(missing))
            return None, None

        # use player.option.customKey for custom match keys (community/endpoint observations)
        # URL-encode all dynamic components
        partyPlayerIds = quote_plus(self.account_ids)
        bucketId = quote_plus(f"{self.netcl}:1:{self.region}:{self.playlist}")
        linkcode = quote_plus(self.link_code)
        partyid = quote_plus(self.party_id)

        ticket_url = (
            f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/"
            f"matchmakingservice/ticket/player/{quote_plus(self.client_id)}"
            f"?partyPlayerIds={partyPlayerIds}"
            f"&bucketId={bucketId}"
            f"&player.platform=Windows"
            f"&player.option.customKey={linkcode}"
            f"&player.option.partyId={partyid}"
            f"&player.input=KBM&player.option.uiLanguage=en"
        )

        # log the full ticket URL (safe for debugging — it contains party_id and link_code)
        logger.info("Ticket URL: " + ticket_url)

        headers = {
            "User-Agent": f"Fortnite/{self.build_version} Windows/10",
            "Authorization": f"bearer {self.bearer}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(ticket_url, headers=headers) as response:
                text = await response.text()
                logger.info(f"Ticket generation: status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    payload = data.get('payload')
                    signature = data.get('signature')
                    if payload and signature:
                        logger.info("Generated matchmaking ticket")
                        return payload, signature
                    else:
                        logger.error("Ticket missing payload/signature: " + json.dumps(data))
                        return None, None
                else:
                    # log response body for debugging
                    logger.error("Ticket generation error body: " + text)
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
                        logger.info(f"WebSocket message: {message}")
                        return {"status": "info", "message": message}
        except Exception as e:
            logger.error(f"Failed to connect websocket: {e}")
            return {"status": "error", "message": str(e)}

    async def check_matchmaking_ban(self):
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{quote_plus(self.client_id)}"
        headers = {
            "User-Agent": f"Fortnite/{self.build_version} Windows/10",
            "Authorization": f"bearer {self.bearer}"
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                logger.info(f"Ban check: status {response.status}")
                text = await response.text()
                try:
                    data = await response.json()
                except Exception:
                    logger.error("Ban check non-json body: " + text)
                    return False
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

            # set presence (attempt namespaced endpoint then fallback)
            presence_ok = await self.set_presence()
            if not presence_ok:
                logger.warning("Presence update failed. Proceeding could fail if Epic requires presence for party operations.")

            # We skip creating a party here; require an existing party_id
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
    # command usage: !startcustom <link_code> <party_id>
    if link_code is None:
        await ctx.send("Usage: `!startcustom <link_code> <party_id>`")
        return
    # basic validation for link code length (Fortnite expects 4-16 chars, no special chars)
    if not (4 <= len(link_code) <= 16 and link_code.isalnum()):
        await ctx.send("Error: Link code must be 4-16 alphanumeric characters.")
        return

    if party_id is None:
        # try environment fallback
        party_id = os.getenv("PARTY_ID")
    if not party_id:
        await ctx.send("Error: No party_id provided. Provide existing party_id as second argument or set PARTY_ID env var.")
        return

    playlist = os.getenv("PLAYLIST", "playlist_defaultsolo")
    mms = DontMessWithMMS(
        account_ids=[os.getenv("ACCOUNT_ID", "ced24960d641410390aef731202c0ae2")],
        client_id=os.getenv("CLIENT_ID", "ced24960d641410390aef731202c0ae2"),
        device_id=os.getenv("DEVICE_ID", "87fd14d15b954a839a9e474b8fed3eb3"),
        secret=os.getenv("SECRET"),
        playlist=playlist,
        link_code=link_code,
        region=os.getenv("REGION", "EU"),
        party_id=party_id,
        fill=False
    )
    result = await mms.start()
    await ctx.send(f"Custom match status: {result.get('message')}")

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
