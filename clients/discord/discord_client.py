import math
import base64
import hashlib
from functools import wraps
from data.config import logger

from data.session import BaseAsyncSession
from db_api.database import Accounts
from utils.headers import create_x_super_properties, create_x_context_properties


class DiscordClient:

    def __init__(self, data: Accounts, session: BaseAsyncSession, version: str, platform: str):
        self.data = data
        self.auth_token = data.discord_token
        self.pubkey = data.sol_address
        self.version = version
        self.platfrom = platform

        self.async_session = session

    async def login(self):

        response = await self.async_session.get('https://discord.com/api/v9/quests/@me', headers=self.base_headers())

        if response.status_code == 200:
            return True
        return False

    @staticmethod
    def open_session(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            #try:
                status = await self.login()
                if status:
                    return await func(self, *args, **kwargs)
                else:
                    return False, f'[{self.data.id}] | {self.pubkey} не смог послать первый запрос. Проверьте дискорд токен!', ''
            # except Exception as e:
            #     return False, 'BAD'
        return wrapper
    
    @open_session
    async def check_if_user_on_server(self):
        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://discord.com',
            'priority': 'u=1, i',
            'referer': 'https://discord.com/channels/@me',
            'sec-ch-ua': self.data.user_agent,
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.async_session.user_agent,
            'x-context-properties': create_x_context_properties(1020496431959785503, 1022621132584648814),
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'Europe/Paris',
            'x-super-properties': create_x_super_properties(),
        }

        json_data = {
            'session_id': ''
        }

        response = await self.async_session.post(
            f"https://discord.com/api/v9/invites/eclipse-fnd",
            json=json_data,
            headers=headers
        )
        # print(response.text)
        # print(response.status_code)
        if "You need to update your app to join this server." in response.text or "captcha_rqdata" in response.text:
            return False, 'user not join at eclipse-fnd server', ''
        if "Unauthorized" in response.text:
            return False, 'user not authorized! Check your token', ''
        return True, '', ''
    
    @open_session
    async def start_oauth2(self, second_try=False):
        
        state, _, _ = self.generate_auth_params(public_key=self.pubkey)
 
        if second_try:
            state = state + '='
        status, url = await self.confirm_auth_code(        
            client_id='1247890907286605834',
            response_type='code',
            redirect_uri='https://eclipse.alldomains.id/api/link/discord',
            scope='identify guilds.members.read',
            state=state, 
        )
        if status:
            return True, f'[{self.data.id}] | {self.pubkey} успешно привязал discord к turbo tap', url
        return False, f'[{self.data.id}] | {self.pubkey} не смог привязать discord к turbo tap', ''

    async def confirm_auth_code(self, client_id, response_type, redirect_uri, scope, state):

        url = "https://discord.com/api/v9/oauth2/authorize"
        headers = self.base_headers()
        headers['referer'] = f'https://discord.com/oauth2/authorize?client_id={client_id}&response_type={response_type}&redirect_uri=https%3A%2F%2Feclipse.alldomains.id%2Fapi%2Flink%2Fdiscord&scope=identify+guilds.members.read&state={state}'

        params = {
            "client_id": client_id,
            "response_type": response_type,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        }

        json_data = {
            'permissions': '0',
            'authorize': True,
            'integration_type': 0,
            'location_context': {
                'guild_id': '10000',
                'channel_id': '10000',
                'channel_type': 10000,
            },
        }

        response = await self.async_session.post(
            url,
            params=params,
            headers=headers,
            json=json_data,
        )

        if response.status_code == 200:
            return True, response.json().get("location")
        logger.error(f'Не смог послать запрос на confirm_auth_code discord. Status code {response.status_code}. Ответ сервера: {response.text}')
        return False, ''

    @staticmethod
    def generate_auth_params(public_key: str):
        """
        Возвращает кортеж (state, code_verifier, code_challenge).
        """
        # 1) Генерация state: b64(public_key), оставляя одну '=' на конце
        state_b64 = base64.b64encode(public_key.encode()).decode()
        # чтобы соответствовать примерам, можно убрать все '=' и добавить одну
        state = state_b64.rstrip('=') + '='

        # 2) Генерация code_verifier:
        #    повтор public_key floor(128 / len(public_key)) раз, берём первые 128 символов
        repeated = public_key * math.floor(128 / len(public_key))
        code_verifier = repeated[:128]

        # 3) Генерация code_challenge:
        #    SHA-256 от code_verifier → base64 → вручную заменить + на - и / на _ и убрать =
        sha256_bytes = hashlib.sha256(code_verifier.encode()).digest()
        sha256_b64 = base64.b64encode(sha256_bytes).decode()
        code_challenge = sha256_b64.replace('+', '-').replace('/', '_').replace('=', '')

        return state, code_verifier, code_challenge

    def base_headers(self):
        return {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': self.auth_token,
            'priority': 'u=1, i',
            'referer': 'https://discord.com/channels/@me',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.async_session.user_agent,
            'x-debug-options': 'bugReporterEnabled',
            'x-discord-locale': 'en-US',
            'x-discord-timezone': 'Europe/Warsaw',
            'x-super-properties': create_x_super_properties(self.async_session.user_agent),
        }