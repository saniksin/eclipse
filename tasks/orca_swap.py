import random
import secrets
from datetime import datetime, timedelta, timezone

from tasks import Base
from clients.sol.sol_client import SolanaClient
from data.config import logger
from data.models import Networks, ECLIPSE_TOKEN
from settings.settings import SWAP_SETTINGS, RPC_DICT, USE_SWAP_LIMIT_PER_DATA, SWAP_DATA_LIMIT
from data.eth_convertor import TokenAmount
from utils.get_amount import get_amount


class OrcaSwap(Base):
    
    def __init__(self, data):
        super().__init__(data)
        self.sol_client = SolanaClient(self.data.sol_pk, self.data.proxy, RPC_DICT['ECLIPSE'])
        self.network = Networks.Eclipse
        self.swap_settings = SWAP_SETTINGS['ORCA']
        self.token = ECLIPSE_TOKEN

    def get_headers(self):
        return {
            'accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'origin': 'https://www.orca.so',
            'priority': 'u=1, i',
            'referer': 'https://www.orca.so/',
            'sec-ch-ua': f'"Google Chrome";v="{self.version}", "Chromium";v="{self.version}", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': f'"{self.platfrom}"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': self.data.user_agent,
        }

    async def orca_swap_quote(self, token_from: str, token_to: str, amount: TokenAmount):

        params = {
            'from': token_from,
            'to': token_to,
            'amount': amount.Wei,
            'isLegacy': 'true',
            'amountIsInput': 'true',
            'includeData': 'true',
            'includeComputeBudget': 'false',
            'maxTxSize': '1200',
            'wallet': self.data.sol_address,
        }

        response = await self.async_session.get(
           'https://pools-api-eclipse.mainnet.orca.so/swap-quote', 
           params=params, 
           headers=self.get_headers()
        )

        if response.status_code == 200:
            answer = response.json()
            return True, answer['data']['swap']
        logger.error(f'[{self.data.id}] | {self.data.sol_address} | Не смог создать quote orca | код ответа сервера - {response.status_code}. Ответ сервера: {response.text}')
        return False, None
    
    
    async def get_instructions(self, tx_quote):

        json_data = {
            'amountIsInput': True,
            'swap': tx_quote,
            'wallet': self.data.sol_address,
            'slippage': '0.005',
        }

        response = await self.async_session.post(
            'https://pools-api-eclipse.mainnet.orca.so/swap-prepare-instructions', 
            headers=self.get_headers(), 
            json=json_data
        )

        if response.status_code == 200:
            answer = response.json()
            return True, answer['data']['instructions'], answer['data']['lookupTableAccounts'], answer['data']['signers']
        logger.error(f'[{self.data.id}] | {self.data.sol_address} | Не смог создать quote orca | код ответа сервера - {response.status_code}. Ответ сервера: {response.text}')
        return False, None
            
    @Base.retry
    async def swap_native_to_token(self, token_to_swap = None, amount_eth_to_dep = None):

        data = ''
        if token_to_swap:
            swap_to = token_to_swap
        else:
            swap_to = secrets.choice(self.swap_settings['SWAP_ETH_TO'])

        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))
        logger.info(f'[{self.data.id}] | {self.data.sol_address} | текущий баланс {self.network.coin_symbol} {current_balance.Ether}')

        if amount_eth_to_dep:
            get_swap_eth_amount = amount_eth_to_dep
        else:

            if self.swap_settings['USE_STATIC_AMOUNT']:
                get_swap_eth_amount = TokenAmount(get_amount(self.swap_settings['NATIVE_ETH_TO_SWAP']), decimals=9)
            else:
                percent_eth_to_swap = secrets.randbelow(
                    self.swap_settings['PERCENT_ETH_TO_SWAP'][1] - self.swap_settings['PERCENT_ETH_TO_SWAP'][0] + 1
                ) + self.swap_settings['PERCENT_ETH_TO_SWAP'][0]
                get_swap_eth_amount = TokenAmount(int((current_balance.Wei / 100) * percent_eth_to_swap), 9, wei=True)
        
        if current_balance.Wei <= get_swap_eth_amount.Wei + self.min_eclipse_eth_amount.Wei:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                         f'Необходимо для свапа {get_swap_eth_amount.Ether} {self.network.coin_symbol} '
                         f'+ комиссия. Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}.')
            
            return True
        
        logger.info(f'[{self.data.id}] | {self.data.sol_address} | начинаю свап {get_swap_eth_amount.Ether} {self.network.coin_symbol} to {swap_to}')
        
        token_from = token_from=self.token['ETH']['token_address']
        token_to = self.token[swap_to]['token_address']

        status, tx_quote = await self.orca_swap_quote(
            token_from=token_from, 
            token_to=token_to, 
            amount=get_swap_eth_amount
        )
        if status:
            status, instructions, address_table_lookups, signers = await self.get_instructions(tx_quote)
            if status:
                token_balance_before_swap = TokenAmount(*(await self.sol_client.get_token_balance(self.token[swap_to])))
                status, data = await self.sol_client.swap_tx_orca(instructions, address_table_lookups, signers)
                if status:
                    token_balance_after_swap = TokenAmount(*(await self.sol_client.get_token_balance(self.token[swap_to])))
                    token_difference = token_balance_after_swap.Ether - token_balance_before_swap.Ether
                    logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно свапнул {get_swap_eth_amount.Ether} {self.network.coin_symbol} на {token_difference} {swap_to}. Tx hash: {self.network.explorer}{data}')
                    if USE_SWAP_LIMIT_PER_DATA and not token_to_swap:
                        day = random.randint(SWAP_DATA_LIMIT[0], SWAP_DATA_LIMIT[1])
                        self.data.swap = datetime.now(timezone.utc) + timedelta(days=day)
                        await self.write_to_db()
                        logger.info(f'[{self.data.id}] | {self.data.sol_address} | следующий свап будет возможен {str(self.data.swap).split(' ')[0]}')
                    return True
        if data:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог свапнуть {self.network.coin_symbol} на {swap_to}. Ответ: {data}.')
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог свапнуть {self.network.coin_symbol} на {swap_to}.')
        return False

    @Base.retry
    async def swap_token_to_native(self):

        data = ''

        usd_value, token, balance = await self.check_token_balances()
        if not token:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | Невозможно сделать свап. Нету токенов...')
            return True

        if usd_value < self.swap_settings['MIN_TOKEN_SWAP_USD_VALUE']:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | Невозможно сделать свап. Текущий USD value токена {token} '
                         f'{usd_value}. MIN_TOKEN_SWAP_USD_VALUE для свапа {self.swap_settings['MIN_TOKEN_SWAP_USD_VALUE']} USD')
            return True
        
        native_token_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))

        if native_token_balance.Ether <= self.min_eclipse_eth_amount.Ether:
            logger.error(
                f'[{self.data.id}] | {self.data.sol_address} | Невозможно сделать свап. Текущий баланс {self.network.coin_symbol} '
                f'меньше или равно {self.min_eclipse_eth_amount.Ether}. Баланс: {native_token_balance.Ether} {self.network.coin_symbol} | MIN_ECLIPSE_ETH_AMOUNT = {self.min_eclipse_eth_amount.Ether}')
            return True

        token_from = self.token[token]['token_address']
        token_to = self.token['ETH']['token_address']

        status, tx_quote = await self.orca_swap_quote(
            token_from=token_from, 
            token_to=token_to, 
            amount=balance
        )

        if status:
            status, instructions, address_table_lookups, signers = await self.get_instructions(tx_quote)
            if status:
                native_balance_before_swap = TokenAmount(*(await self.sol_client.get_token_balance(native=True)))
                status, data = await self.sol_client.swap_tx_orca(instructions, address_table_lookups, signers)
                if status:
                    native_balance_after_swap = TokenAmount(*(await self.sol_client.get_token_balance(native=True)))
                    token_difference = native_balance_after_swap.Ether - native_balance_before_swap.Ether
                    logger.success(f'[{self.data.id}] | {self.data.sol_address} | успешно свапнул {balance.Ether} {token} на {token_difference} {self.network.coin_symbol}. Tx hash: {self.network.explorer}{data}')
                    
                    if USE_SWAP_LIMIT_PER_DATA:
                        day = random.randint(SWAP_DATA_LIMIT[0], SWAP_DATA_LIMIT[1])
                        self.data.swap = datetime.now(timezone.utc) + timedelta(days=day)
                        await self.write_to_db()
                        logger.info(f'[{self.data.id}] | {self.data.sol_address} | следующий свап будет возможен {str(self.data.swap).split(' ')[0]}')
                    return True
    
        if data:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог свапнуть {token} на {self.network.coin_symbol}. Ответ: {data}.')
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} | не смог свапнуть {token} на {self.network.coin_symbol}.')
        return False