import os
import json
import hashlib
import logging
import asyncio
import aiohttp
import ast
from urllib.parse import quote_plus
from aiohttp import web
import discord
from discord.ext import commands

# ---------------------------
# Logging setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("fortnite-custom")

class DontMessWithMMS:
    def __init__(self, **kwargs):
        self.account_ids = kwargs.pop('account_ids', [])
        self.client_id = kwargs.pop('client_id')
        self.device_id = kwargs.pop('device_id')
        self.secret = kwargs.pop('secret')
        self.playlist = kwargs.pop('playlist', "playlist_defaultsolo")
        self.link_code = kwargs.pop('link_code', None)
        self.region = kwargs.pop('region', "EU").upper()
        self.party_id = kwargs.pop('party_id', None)
        self.fill = kwargs.pop('fill', False)

        self.token_data = None
        self.bearer = None
        self.client_credentials_token = None
        self.netcl = None

        # Fortnite client auth (base64 client_id:client_secret)
        self.fortnite_auth = os.getenv("FORTNITE_AUTH")

        # User-Agent template (will update when netcl is fetched)
        self.user_agent = f"Fortnite/++Fortnite+Release-37.30-CL-0 Windows/10"

    async def create_token(self):
        """Get bearer token using Device Auth"""
        if not self.fortnite_auth:
            logger.error("FORTNITE_AUTH env var not set. Cannot authenticate.")
            return None

        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"basic {self.fortnite_auth}"
        }
        data = {
            "grant_type": "device_auth",
            "account_id": self.client_id,
            "device_id": self.device_id,
            "secret": self.secret
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as resp:
                logger.info(f"Token creation: status {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    self.token_data = data
                    self.bearer = data.get("access_token")
                    logger.info("Fetched bearer token")
                    return data
                else:
                    error_body = await resp.text()
                    logger.error("Token creation failed: " + error_body)
                    return None

    async def client_credentials(self):
        """Get client credentials token"""
        if not self.fortnite_auth:
            logger.error("FORTNITE_AUTH env var not set. Cannot authenticate client credentials.")
            return

        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"basic {self.fortnite_auth}"
        }
        data = {"grant_type": "client_credentials"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=headers) as resp:
                logger.info(f"Client credentials: status {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    self.client_credentials_token = data.get("access_token")
                    logger.info("Fetched client credentials token")
                else:
                    error_body = await resp.text()
                    logger.error("Client credentials failed: " + error_body)

    async def get_netcl(self):
        """Fetch NetCL build number for current Fortnite version"""
        url = "https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/version"
        headers = {"Authorization": f"bearer {self.bearer}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                logger.info(f"Netcl fetch attempt 1: status {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    netcl = data.get("cln") or data.get("build")
                    if netcl:
                        self.netcl = netcl
                        # Update User-Agent with real build number
                        self.user_agent = f"Fortnite/++Fortnite+Release-37.30-CL-{netcl} Windows/10"
                    return netcl
                else:
                    error_body = await resp.text()
                    logger.error("Netcl fetch failed: " + error_body)
                    return None

    async def set_presence(self):
        """Try to set presence (not critical but recommended)"""
        url1 = f"https://presence-public-service-prod.ol.epicgames.com/presence/api/v1/fortnite/{self.client_id}/presence"
        url2 = f"https://presence-public-service-prod.ol.epicgames.com/presence/api/v1/_/{self.client_id}/presence"
        headers = {
            "Authorization": f"bearer {self.bearer}",
            "Content-Type": "application/json"
        }
        payload = {"status": "online", "isPlaying": True, "isJoinable": True}
        async with aiohttp.ClientSession() as session:
            async with session.post(url1, headers=headers, json=payload) as resp1:
                logger.info(f"Presence update attempt at {url1} -> status {resp1.status}")
                if resp1.status == 200:
                    return True
                else:
                    logger.error(f"Presence endpoint {url1} returned {resp1.status}: {await resp1.text()}")
            async with session.put(url2, headers=headers, json=payload) as resp2:
                logger.info(f"Presence update attempt at {url2} with PUT -> status {resp2.status}")
                if resp2.status == 200:
                    return True
                else:
                    logger.error(f"Presence endpoint {url2} returned {resp2.status}: {await resp2.text()}")
                    return False
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

        ticket_url = (
            f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/"
            f"matchmakingservice/ticket/player/{quote_plus(self.client_id)}"
            f"?partyPlayerIds={quote_plus(self.client_id)}"
            f"&bucketId={quote_plus(f'{self.netcl}:1:{self.region}:{self.playlist}')}"
            f"&player.platform=Windows"
            f"&player.option.customKey={quote_plus(self.link_code)}"
            f"&player.option.partyId={quote_plus(self.party_id)}"
            f"&player.input=KBM&player.option.uiLanguage=en"
        )

        logger.info("Ticket URL: " + ticket_url)

        headers = {"User-Agent": self.user_agent, "Authorization": f"bearer {self.bearer}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(ticket_url, headers=headers) as response:
                logger.info(f"Ticket generation: status {response.status}")
                text = await response.text()
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
                    logger.error("Ticket generation error body: " + text)
                    return None, None

    async def connect_websocket(self, payload, signature, checksum):
        if not all([payload, signature, checksum]):
            return {"status": "error", "message": "Invalid ticket data"}
        headers = {"Authorization": f"Epic-Signed mms-player {payload} {signature} {checksum}",
                   "User-Agent": self.user_agent}
        uri = f"wss://fortnite-matchmaking-public-service-live-{self.region}.ol.epicgames.com:443"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(uri, headers=headers) as ws:
                    logger.info("WebSocket connection opened")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            parsed = ast.literal_eval(msg.data)
                            if parsed.get("name") == "Play":
                                logger.info("Matchmaking process successful")
                                return {"status": "success",
                                        "message": f"Custom match started with link code: {self.link_code} (party: {self.party_id})"}
                            else:
                                logger.info(f"WebSocket message: {msg.data}")
                                return {"status": "info", "message": msg.data}
        except Exception as e:
            logger.error(f"Failed to connect websocket: {e}")
            return {"status": "error", "message": str(e)}

    async def check_matchmaking_ban(self):
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{quote_plus(self.client_id)}"
        headers = {"User-Agent": self.user_agent, "Authorization": f"bearer {self.bearer}"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                logger.info(f"Ban check: status {response.status}")
                try:
                    data = await response.json()
                except Exception:
                    logger.error("Ban check non-json body: " + await response.text())
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

            presence_ok = await self.set_presence()
            if not presence_ok:
                logger.warning("Presence update failed. Proceeding anyway.")

            if not self.party_id:
                return {"status": "error", "message": "No party_id provided."}

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

# ---------------------------
# Discord Bot Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Bot logged in as {bot.user}")

@bot.command(name='startcustom')
async def start_custom(ctx, link_code=None, party_id=None):
    if link_code is None:
        await ctx.send("Usage: `!startcustom <link_code> <party_id>`")
        return
    if not (4 <= len(link_code) <= 16 and link_code.isalnum()):
        await ctx.send("Error: Link code must be 4-16 alphanumeric characters.")
        return

    if party_id is None:
        party_id = os.getenv("PARTY_ID")
    if not party_id:
        await ctx.send("Error: No party_id provided. Provide it or set PARTY_ID env var.")
        return

    playlist = os.getenv("PLAYLIST", "playlist_defaultsolo")
    mms = DontMessWithMMS(
        account_ids=[os.getenv("ACCOUNT_ID", "ced24960d641410390aef731202c0ae2")],
        client_id=os.getenv("ACCOUNT_ID", "ced24960d641410390aef731202c0ae2"),
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

# ---------------------------
# Health check server + Runner
# ---------------------------
async def health_check(request):
    return web.json_response({"status": "ok"})

app = web.Application()
app.router.add_get('/health', health_check)

async def start_web_and_bot():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 10000)))
    await site.start()
    await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(start_web_and_bot())
