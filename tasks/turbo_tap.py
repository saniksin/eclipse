import json
import asyncio
import random
from datetime import datetime, timezone


from tasks import Base
from clients.sol.sol_client import SolanaClient
from settings.settings import RPC_DICT, SLEEP_BEETWEEN_START_TAP_ACTIONS, CLAIM_DOMAIN_VIA
from data.config import logger, PARSE_CODES, tasks_lock
from data.models import Networks, TokenAmount
from clients.twitter.twitter_client import TwitterClient
from clients.discord.discord_client import DiscordClient
from functools import wraps


class TurboTap(Base):

    def __init__(self, data):
        super().__init__(data)
        self.sol_client = SolanaClient(self.data.sol_pk, self.data.proxy, RPC_DICT['ECLIPSE'])
        self.network = Networks.Eclipse
        self.auth_token = ''

    @Base.retry
    async def start_turbo_tap(self):

        async with tasks_lock:
            sleep_time = random.randint(SLEEP_BEETWEEN_START_TAP_ACTIONS[0], SLEEP_BEETWEEN_START_TAP_ACTIONS[1])
            logger.info(f'[{self.data.id}] | {self.data.sol_address} сон {sleep_time} секунд перед началом тапов...')
            await asyncio.sleep(sleep_time)
        
        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))

        if current_balance.Ether < self.min_eclipse_eth_amount.Ether:
            logger.error(
                f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. MIN_ECLIPSE_ETH_BALANCE: {self.min_eclipse_eth_amount.Ether} {self.network.coin_symbol}'
            )
            return True
        
        if not self.data.turbo_tap_pk:
            self.data.turbo_tap_pk = self.sol_client.get_solana_pk()
            await self.write_to_db()
            logger.info(f'[{self.data.id}] | {self.data.sol_address} | успешно сгененировал приватный ключ игрового аккаунта.')

        if not self.data.turbo_tap_pubkey:
            
            logger.info(f'[{self.data.id}] | {self.data.sol_address} | пробую отправить транзакцию для регистрации пары PK и PubKey для TurboTap.')

            status, tap_pub_key, tx_hash = await self.sol_client.start_register_tap_acc(self.data)

            if "depositold" in status:
                self.data.turbo_tap_pubkey = tap_pub_key
                await self.write_to_db()
                logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно пополнил старый игровой аккаунт TurboTap. Tx hash: {self.network.explorer}{tx_hash}')

            if "already used" in status:
                self.data.turbo_tap_pubkey = tap_pub_key
                await self.write_to_db()
                logger.warning(f'[{self.data.id}] | {self.data.sol_address} | {tx_hash}')

            if status == 'success':
                self.data.turbo_tap_pubkey = tap_pub_key
                await self.write_to_db()
                logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно создал пару PK и PubKey для TurboTap. Tx hash: {self.network.explorer}{tx_hash}')

            elif status == 'tx_fail':
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог создать пару PK и PubKey для TurboTap. Tx hash: {self.network.explorer}{tx_hash}')
                return False
            
            elif status == 'error':
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог создать пару PK и PubKey для TurboTap. Ошибка: {tx_hash}')
                return False
            
        if self.data.turbo_tap_pubkey and self.data.turbo_tap_pk:

            status = await self.sol_client.start_tap(self.data)
            if status:
                self.data.turbo_tap_tap_finished = True
                await self.write_to_db()
                logger.info(f'[{self.data.id}] | {self.data.sol_address} | успешно закончил тапать на TurboTap')
                return True

        return False
    
    def get_base_headers(self):
        return {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'text/plain;charset=UTF-8',
            'origin': 'https://tap.eclipse.xyz',
            'priority': 'u=1, i',
            'referer': 'https://tap.eclipse.xyz/',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.data.user_agent,
        }
        

    async def get_account_handlers(self):

        data = json.dumps({"pubkey": self.data.sol_address})

        response = await self.async_session.post('https://tap.eclipse.xyz/api/handles', headers=self.get_base_headers(), data=data)

        if response.status_code == 200:
            return True, response.json()
        logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог получить handlers TurboTap. Ответ сервера: {response.text} | Status code {response.status_code}')
        return False, ''

    async def get_confirm_request(self, url):
        
        response = await self.async_session.get(url, headers=self.get_base_headers())
        if response.status_code == 200:
            return True
        return False

    async def get_domain_info(self):
        headers = {
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'Referer': 'https://eclipse.alldomains.id/',
            'User-Agent': self.data.user_agent,
            'Accept': 'application/json, text/plain, */*',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'x-onsol-chain': 'ECLIPSE',
            'sec-ch-ua-mobile': '?0',
        }

        response = await self.async_session.get(
            f'https://api.alldomains.id/user-profile/{self.data.sol_address}',
            headers=headers,
        )

        if response.status_code == 200:
            return True, response.json()['mainDomain']
        return False, ''
    
    async def get_domain_claim_info(self):

        json_data = {
            'pubkey': self.data.sol_address,
        }

        response = await self.async_session.post('https://tap.eclipse.xyz/api/records/claim', headers=self.get_base_headers(), json=json_data)
        if response.status_code == 200:
            return True, response.json()['transaction']
        logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог получить get_domain_claim_info. Status code: {response.status_code} | Ответ сервера: {response.text}')
        return False, ''

    async def get_domain_claim_info_via_all_domains(self):
        headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://eclipse.alldomains.id',
            'priority': 'u=1, i',
            'referer': 'https://eclipse.alldomains.id/register-domain',
            'sec-ch-ua': f'"Not A(Brand";v="8", "Chromium";v="{self.version}", "Google Chrome";v="{self.version}"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': self.data.user_agent,
        }

        json_data = {
            'simulate': True,
            'durationRate': 0,
            'pubkey': self.data.sol_address,
            'userWindowSize': random.randint(1000, 2500),
        }

        response = await self.async_session.post('https://eclipse.alldomains.id/api/handle-link', headers=headers, json=json_data)
        if response.status_code == 200:
            answer = response.json()
            if answer.get('status', '') == 'success':
                tx = answer.get('transaction', '')
                if tx:
                    return True, tx
        logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог получить get_domain_claim_info_via_all_domains. Status code: {response.status_code} | Ответ сервера: {response.text}')
        return False, ''

    async def check_if_user_onboarded(self):
        
        # Формируем текущее время в формате UTC
        current_time = datetime.now(timezone.utc)

        # Форматируем дату и время
        formatted_date = current_time.strftime("%Y-%m-%d %H:%M:%S")

        # Получаем временную метку (timestamp в миллисекундах)
        timestamp = int(current_time.timestamp() * 1000)

        # Формируем сообщение
        message = f"Login to Eclipse\nDate: {formatted_date}\nTimestamp: {timestamp}"


        signed_message = self.sol_client.account.sign_message(message.encode('utf-8'))

        json_data = {
            'signed_message': str(signed_message),
            'original_message': message,
            'public_key': self.data.sol_address,
            'is_ledger': False,
        }

        response = await self.async_session.post(
            'https://tap.eclipse.xyz/api/eclipse/user/login', 
            headers=self.get_base_headers(), 
            json=json_data
        )
        
        return response.text

    async def send_onboard_tx(self, tx_data):

        data = json.dumps({
            "signed_transaction": tx_data
        })

        response = await self.async_session.post('https://tap.eclipse.xyz/api/eclipse/user/onboard', headers=self.get_base_headers(), data=data)
        if response.status_code == 200:
            return True, response.text
        return False, response.text

    async def sleep_after_action(self, action):
        sleep_time = random.randint(30, 60)
        logger.info(f'[{self.data.id}] | {self.data.sol_address} | сон {sleep_time} секунд после действия {action}')
        await asyncio.sleep(sleep_time)

    @Base.retry
    async def start_registration(self):
        twitter_status, discord_status, domain_status, second_try = False, False, False, False

        status, account_info = await self.get_account_handlers()
        twitter_account = account_info.get('handle', {}).get('x', '')

        if not status:
            return False
        
        if "No X handle found for the given pubkey" in str(account_info) or not twitter_account:

            logger.info(f"[{self.data.id}] | {self.data.sol_address} начинаю привязку twitter аккаунта")
            
            twitter = TwitterClient(self.data, self.async_session, self.version, self.platfrom)   
            status, answer, url = await twitter.start_oauth2()
            if not status:
                logger.error(answer)
                return False

            status = await self.get_confirm_request(url)
            
            if not status:
                second_try = True
                status, answer, url = await twitter.start_oauth2(second_try=True)
                if not status:
                    logger.error(answer)
                    return False
                
                status = await self.get_confirm_request(url)
                if not status:
                    logger.error(f'[{self.data.id}] | {self.data.sol_address} | возникла ошибка при подтверждение привязки twitter')
                    return False
            
            status, account_info = await self.get_account_handlers()  
            twitter_account = account_info.get('handle', {}).get('x', {})
            if not twitter_account:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог привязать твиттер к аккаунту. Проверьте токен!')
                return True
            
            twitter_status = True

            logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно привязал twitter @{twitter_account} к TurboTap!')

            await self.sleep_after_action('add twitter')
        
        twitter_account = account_info.get('handle', {}).get('x', {})
        
        if twitter_account and not twitter_status:
            logger.success(f'[{self.data.id}] | {self.data.sol_address} | твиттер аккаунт @{twitter_account} успешно привязан!')

        discord_account = account_info.get('handle', {}).get('discord', {})

        if not discord_account:

            logger.info(f"[{self.data.id}] | {self.data.sol_address} начинаю привязку discord аккаунта")
            discord = DiscordClient(self.data, self.async_session, self.version, self.platfrom)
            # status, msg, _ = await discord.check_if_user_on_server()
            # if not status:
            #     logger.error(f'[{self.data.id}] | {self.data.sol_address} {msg}')
            #     return True

            status, answer, url = await discord.start_oauth2(second_try)
            if not status:
                logger.error(answer)
                return False
            
            status = await self.get_confirm_request(url)
            
            if not status:
                status, answer, url = await discord.start_oauth2(second_try=True)
                if not status:
                    logger.error(answer)
                    return False
                
                status = await self.get_confirm_request(url)
                if not status:
                    logger.error(f'[{self.data.id}] | {self.data.sol_address} | возникла ошибка при подтверждение привязки discord')
                    return False
            
            status, account_info = await self.get_account_handlers()
            
            discord_account = account_info.get('handle', {}).get('discord', {})
            if not discord_account:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог привязать discord аккаунт. Проверьте токен!')
                return True
            
            logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно привязал discord id {discord_account} к TurboTap!')

            discord_status = True

            await self.sleep_after_action('add discord')

        if discord_account and not discord_status:
            logger.success(f'[{self.data.id}] | {self.data.sol_address} | discord id {discord_account} успешно привязан!')
        
        status, domain = await self.get_domain_info()
        
        if not status:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог спарсить информацию про domain')
            return False
        
        if not domain:
            logger.info(f"[{self.data.id}] | {self.data.sol_address} начинаю клейм домена {twitter_account}")

            if CLAIM_DOMAIN_VIA == 'TurboTap':
                status, tx_data = await self.get_domain_claim_info()
                if not status:
                    logger.error(f'[{self.data.id}] | {self.data.sol_address} | возникла ошибка при попытке получить claim domain tx_data via get_domain_claim_info')
                    return False
    
            elif CLAIM_DOMAIN_VIA == 'AllDomains':
                status, tx_data = await self.get_domain_claim_info_via_all_domains()
                if not status:
                    logger.error(f'[{self.data.id}] | {self.data.sol_address} | возникла ошибка при попытке получить claim domain tx_data via get_domain_claim_info_via_all_domains')
                    return False
            else:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | не верный CLAIM_DOMAIN_VIA в настройках! Доступно TurboTap или AllDomains')

            status, data = await self.sol_client.tx_v0_via_ready_data(tx_data)
            if not status:
                if 'already in use' not in str(data):
                    logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог сминтить domain turbotap. Ответ: {data}')
                    return False
                domain = True
            else:
                logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно сминтил domain {twitter_account} на turbotap. Tx hash: {self.network.explorer}{data}')
            
            domain_status = True
            if not domain:
                await self.sleep_after_action('claim domain')

        status, domain = await self.get_domain_info()

        if domain and not domain_status:
            logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно сминтил domain {domain}!')


        onboarded_status = await self.check_if_user_onboarded()

        if "User not found" in onboarded_status:
            logger.info(f'[{self.data.id}] | {self.data.sol_address} | пробую отправить onboard tx')

            status, tx_data = await self.sol_client.get_tx_base_64(self.data)
            if not status:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог подготовить транзакцию на onboard. Ответ: {tx_data}')
                return False

            status, msg = await self.send_onboard_tx(tx_data)
            if "Invite code already used" in msg:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | реф код {self.data.turbo_tap_ref_code} уже был использован. Ответ: {tx_data}')
                self.data.turbo_tap_ref_code = ''
                await self.write_to_db()
                return True
            elif not status:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог отправить транзакцию onboarding. Ответ: {msg}')
                sleep_time = random.randint(20, 60)
                logger.info(f'[{self.data.id}] | {self.data.sol_address} | сон {sleep_time} секунд перед след попыткой')
                await asyncio.sleep(sleep_time)
                return False
            else:
                logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно прошел onboarding. Ответ: {status}')

        self.data.turbo_tap_is_registered = True
        await self.write_to_db()
        logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно закончил регистрацию в turbotap.')
        
        return True
    
    @staticmethod
    def tap_login(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            
            answer = await self.check_if_user_onboarded()
            self.auth_token = json.loads(answer).get('token', '')
            return await func(self, *args, **kwargs)

        return wrapper
    
    @Base.retry
    @tap_login
    async def parse_ref_codes(self):

        if self.auth_token:
            headers = self.get_base_headers()
            headers['content-type'] = 'application/json'
            headers['eclipse-authorization'] = f"Bearer {self.auth_token}"


            response = await self.async_session.post(
                'https://tap.eclipse.xyz/api/eclipse/user/referral/code', 
                headers=headers, 
            )
    
            if response.status_code == 200:
                answer = response.json()
                available_codes = [token["code"] for token in answer["referral_codes"] if token["claimed_by"] is None]
                if available_codes:
                    async with tasks_lock:
                        with open(PARSE_CODES, 'a') as file:
                            for code in available_codes:
                                file.write(f'{code}\n')
                        logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно записал все доступные кода в {PARSE_CODES}')
                else:
                    logger.warning(f'[{self.data.id}] | {self.data.sol_address} | нет доступных инвайт кодов либо все использованы') 

        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог вытащить auth_token') 
        return True
    
    @Base.retry
    @tap_login
    async def parse_stats(self):

        if self.auth_token:
            headers = self.get_base_headers()
            headers['content-type'] = 'application/json'
            headers['eclipse-authorization'] = f"Bearer {self.auth_token}"

            response = await self.async_session.post(
                'https://tap.eclipse.xyz/api/eclipse/user/points', 
                headers=headers, 
            )

            if response.status_code == 200:
                answer = response.json().get('data', {})
                required_fields = ['passive_earning_rate', 'points', 'rank']
                if all(field in answer for field in required_fields):
                    self.data.turbo_tap_points = answer['points']
                    self.data.turbo_tap_passive_earning = answer['passive_earning_rate']
                    self.data.turbo_tap_rank = answer['rank']
                    async with tasks_lock:
                        await self.write_to_db()
                    logger.success(
                        f'[{self.data.id}] | {self.data.sol_address} | успешно спарсил данные. '
                        f'TapPoints: {answer['points']} | Passive: {answer['passive_earning_rate']} | Rank: {answer['rank']}'
                    )
                else:
                    logger.warning(
                        f'[{self.data.id}] | {self.data.sol_address} | что-то поменялось в ответе...'
                    )
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог спарсить статистику') 
        
        return True