import uuid
import math
import json
import base64
import secrets
import hashlib
from functools import wraps
from data.config import logger

from data.session import BaseAsyncSession
from db_api.database import Accounts


class TwitterClient:

    def __init__(self, data: Accounts, session: BaseAsyncSession, version: str, platform: str):
        self.data = data
        self.auth_token = data.twitter_token
        self.pubkey = data.sol_address
        self.version = version
        self.platfrom = platform

        self.async_session = session
        self.ct0 = ''

    async def login(self):
        cookies = {
            'auth_token': self.auth_token
        }

        data = {
            'debug': 'true',
            'log': '[{"_category_":"client_event","format_version":2,"triggered_on":1736641509177,"event_info":"String","event_namespace":{"page":"app","action":"error","client":"m5"},"client_event_sequence_start_timestamp":1736640638874,"client_event_sequence_number":130,"client_app_id":"3033300"},{"_category_":"client_event","format_version":2,"triggered_on":1736641510151,"event_info":"String","event_namespace":{"page":"app","action":"error","client":"m5"},"client_event_sequence_start_timestamp":1736640638874,"client_event_sequence_number":131,"client_app_id":"3033300"}]',
        }
        
        response = await self.async_session.post('https://x.com/i/api/1.1/jot/client_event.json', headers=self.base_headers(), cookies=cookies, data=data)

        if response.status_code == 200:
            self.ct0 = self.async_session.cookies['ct0']
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
                    return False, f'[{self.data.id}] | {self.pubkey} не смог послать первый запрос. Проверьте твиттер токен!', ''
            # except Exception as e:
            #     return False, 'BAD'
        return wrapper
    
    @open_session
    async def start_oauth2(self, second_try=False):
        state, _, code_challenge = self.generate_auth_params(public_key=self.pubkey)
        if second_try:
            state = state + '='
        status, auth_code = await self.request_oauth2_auth_code(
            client_id='SU1xcWwyaFdYanJ3bnVUaGxRWjQ6MTpjaQ',
            code_challenge=code_challenge,
            state=state,
            redirect_uri='https://eclipse.alldomains.id/api/link/x-turbo',
            code_challenge_method='s256',
            scope='tweet.read users.read offline.access',
            response_type='code'
        )
        if status:
            status, url = await self.confirm_auth_code(auth_code, state, code_challenge)
            if status:
                return True, f'[{self.data.id}] | {self.pubkey} успешно привязал твиттер к turbo tap', url
        return False, f'[{self.data.id}] | {self.pubkey} не смог привязать twitter к turbo tap', ''

    async def request_oauth2_auth_code(
        self,
        client_id: str,
        code_challenge: str,
        state: str,
        redirect_uri: str,
        code_challenge_method: str,
        scope: str,
        response_type: str,
    ) -> str:
        

        url = "https://x.com/i/api/2/oauth2/authorize"
        headers = self.base_headers()
        headers['x-csrf-token'] = self.ct0

        params = {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope,
        }

        response = await self.async_session.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            auth_code = response.json().get('auth_code')
            return True, auth_code
        logger.error(f'[{self.data.id}] | {self.pubkey} | Не смог послать запрос на получение auth_code twitter. Status code {response.status_code}. Ответ сервера: {response.text}')
        return False, ''
        
    async def confirm_auth_code(self, auth_code, state, code_challenge):

        x_uuid = self.generate_client_uuid()
        transaction_id = self.generate_client_transaction_id()

        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'content-type': 'application/x-www-form-urlencoded',
            'origin': 'https://x.com',
            'priority': 'u=1, i',
            'referer': f'https://x.com/i/oauth2/authorize?response_type=code&client_id=enotMWpLZUttb3ItME0zQUo4Yzg6MTpjaQ&redirect_uri=https%3A%2F%2Feclipse.alldomains.id%2Fapi%2Flink%2Fx-turbo&state={state[:-1]}%3D&code_challenge={code_challenge}&code_challenge_method=s256&scope=tweet.read%20users.read%20offline.access',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.data.user_agent,
            'x-client-transaction-id': transaction_id,
            'x-client-uuid': x_uuid,
            'x-csrf-token': self.ct0,
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
        }

        data = {
            'approval': 'true',
            'code': auth_code,
        }   
        
        response = await self.async_session.post('https://x.com/i/api/2/oauth2/authorize', headers=headers, data=data)

        if response.status_code == 200:
            return True, response.json().get("redirect_uri")
        logger.error(f'Не смог послать запрос на confirm_auth_code twitter. Status code {response.status_code}. Ответ сервера: {response.text}')
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

    @staticmethod
    def generate_client_transaction_id():
        """
        Генерирует случайный x-client-transaction-id в формате Base64.
        """
        random_bytes = secrets.token_bytes(70)  
        transaction_id = base64.b64encode(random_bytes).decode('ascii').rstrip('=')  
        return transaction_id
    
    @staticmethod
    def generate_client_uuid():
        """
        Генерирует случайный x-client-uuid.
        """
        return str(uuid.uuid4())  

    def base_headers(self):
        return {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
            'priority': 'u=1, i',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.data.user_agent,
            'x-client-transaction-id': self.generate_client_transaction_id(),
            'x-client-uuid': self.generate_client_uuid(),
            'x-twitter-active-user': 'yes',
            'x-twitter-auth-type': 'OAuth2Session',
            'x-twitter-client-language': 'en',
        }

