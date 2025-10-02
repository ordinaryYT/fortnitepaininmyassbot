from aiohttp import ClientSession, web
import websockets
import hashlib
import json
import ast
import asyncio
import os

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

    async def get_user_agent(self):
        url = "https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/public/assets/v2/platform/Windows/namespace/fn/catalogItem/4fe75bbc5a674f4f9b356b5c90567da5/app/Fortnite/label/Live"
        headers = {"Authorization": f"bearer {self.client_credentials_token}"}
        try:
            async with ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    data = await response.json()
                    buildVersion = data["elements"][0]["buildVersion"][:-8]
                    return f"Fortnite/{buildVersion} Windows/10"
        except Exception as e:
            print(f"Failed to get user agent: {e}")
            return None

    async def get_netcl(self):
        url = "https://fortnite-public-service-prod11.ol.epicgames.com/fortnite/api/matchmaking/session/matchMakingRequest"
        payload = {"criteria": [], "openPlayersRequired": 1, "buildUniqueId": "", "maxResults": 1}
        headers = {"Authorization": f"bearer {self.bearer}", "Content-Type": "application/json"}
        try:
            async with ClientSession() as session:
                async with session.post(url, data=json.dumps(payload), headers=headers) as response:
                    data = await response.json()
                    self.netcl = data[0]["buildUniqueId"]
                    return self.netcl
        except Exception as e:
            print(f"Failed to get netcl: {e}")
            return None

    async def client_credentials(self):
        url = "https://account-public-service-prod.ol.epicgames.com/account/api/oauth/token"
        payload = {"grant_type": "client_credentials"}
        headers = {"Authorization": f"Basic {LAUNCHER_TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
        try:
            async with ClientSession() as session:
                async with session.post(url, data=payload, headers=headers) as response:
                    data = await response.json()
                    self.client_credentials_token = data['access_token']
                    return data
        except Exception as e:
            print(f"Failed to get client credentials token: {e}")
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
        try:
            async with ClientSession() as session:
                async with session.post(url, data=payload, headers=headers) as response:
                    data = await response.json()
                    self.bearer = data['access_token']
                    self.client_id = data['account_id']
                    return data
        except Exception as e:
            print(f"Failed to get access token: {e}")
            return None

    async def create_party(self):
        url = "https://party-service-prod.ol.epicgames.com/party/api/v1/parties"
        payload = {
            "Theme": "default",
            "Sentinel": {
                "SentinelPlatform": "Windows",
                "SentinelPlatformType": "PC",
                "SentinelVersion": 1
            },
            "Config": {
                "JoinInProgress": True,
                "JoinInProgressLock": False,
                "AllowCrossPlay": True,
                "AcceptInvites": True,
                "ChatEnabled": True,
                "SquadSize": 1
            },
            "Members": [
                {
                    "AccountID": self.client_id,
                    "Role": "LEADER",
                    "Platform": "WIN",
                    "PlatformVersion": "++Fortnite+Release-31.10",
                    "ProductVersion": "31.10-CL-XXXXXXX"
                }
            ]
        }
        headers = {"Authorization": f"bearer {self.bearer}", "Content-Type": "application/json"}
        try:
            async with ClientSession() as session:
                async with session.post(url, data=json.dumps(payload), headers=headers) as response:
                    data = await response.json()
                    self.party_id = data['Id']
                    return self.party_id
        except Exception as e:
            print(f"Failed to create party: {e}")
            return None

    def calculate_checksum(self, ticket_payload, signature):
        try:
            plaintext = ticket_payload[10:20] + "Don'tMessWithMMS" + signature[2:10]
            data = plaintext.encode('utf-16le')
            sha1_hash = hashlib.sha1(data).digest()
            checksum = sha1_hash[2:10].hex().upper()
            return checksum
        except Exception as e:
            print(f"Failed to calculate checksum: {e}")
            return None

    async def generate_ticket(self):
        try:
            url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}?partyPlayerIds={self.account_ids}&bucketId={self.netcl}:1:{self.region}:{self.playlist}&player.platform=Windows&player.subregions=DE,GB,FR&player.option.linkCode={self.playlist}&player.option.fillTeam={self.fill}&player.option.preserveSquad=false&player.option.crossplayOptOut=false&player.option.partyId={self.party_id}&player.option.splitScreen=false&party.WIN=true&input.KBM=true&player.input=KBM&player.option.microphoneEnabled=true&player.option.uiLanguage=en"
            headers = {"User-Agent": await self.get_user_agent(), "Authorization": f"bearer {self.bearer}"}
            async with ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    data = await response.json()
                    payload = data['payload']
                    signature = data['signature']
                    return payload, signature
        except Exception as e:
            print(f"Failed to generate ticket: {e}")
            return None, None

    async def connect_websocket(self, payload, signature, checksum):
        headers = {"Authorization": f"Epic-Signed mms-player {payload} {signature} {checksum}"}
        uri = f"wss://fortnite-matchmaking-public-service-live-{self.region}.ol.epicgames.com:443"
        try:
            async with websockets.connect(uri, extra_headers=headers) as ws:
                print("WebSocket connection opened")
                async for message in ws:
                    if ast.literal_eval(message)["name"] == "Play":
                        print("Matchmaking process successful.")
                        return {"status": "success", "message": "Matchmaking process successful"}
                    else:
                        print(message)
                        return {"status": "info", "message": message}
        except Exception as e:
            print(f"Failed to connect websocket: {e}")
            return {"status": "error", "message": str(e)}

    async def check_matchmaking_ban(self):
        url = f"https://fngw-mcp-gc-livefn.ol.epicgames.com/fortnite/api/game/v2/matchmakingservice/ticket/player/{self.client_id}"
        headers = {"User-Agent": await self.get_user_agent(), "Authorization": f"bearer {self.bearer}"}
        async with ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                data = await response.json()
                return data.get("errorCode", None) == "errors.com.epicgames.fortnite.player_banned_from_sub_game"

    async def start(self):
        try:
            self.token_data = await self.create_token()
            if not self.token_data:
                return {"status": "error", "message": "Failed to authenticate"}
            await self.client_credentials()
            await self.get_netcl()
            is_banned = await self.check_matchmaking_ban()
            if is_banned:
                return {"status": "error", "message": "The client is currently banned from matchmaking"}
            self.party_id = await self.create_party()
            if not self.party_id:
                return {"status": "error", "message": "Failed to create party"}
            payload, signature = await self.generate_ticket()
            if not payload or not signature:
                return {"status": "error", "message": "Failed to generate matchmaking ticket"}
            checksum = self.calculate_checksum(payload, signature)
            print("Connecting to WebSocket")
            return await self.connect_websocket(payload, signature, checksum)
        except Exception as e:
            print(f"An error occurred: {e}")
            return {"status": "error", "message": str(e)}

async def start_matchmaking(request):
    mms = DontMessWithMMS(
        account_ids=["ced24960d641410390aef731202c0ae2"],
        client_id="ced24960d641410390aef731202c0ae2",
        device_id="87fd14d15b954a839a9e474b8fed3eb3",
        secret=os.getenv("SECRET"),
        playlist=os.getenv("PLAYLIST", "GamePlaylist_Solo"),
        region=os.getenv("REGION", "EU"),
        fill=False
    )
    result = await mms.start()
    return web.json_response(result)

app = web.Application()
app.router.add_get('/start', start_matchmaking)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    web.run_app(app, port=port)
