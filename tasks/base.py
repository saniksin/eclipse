import json
import asyncio
from functools import wraps

from sqlalchemy.ext.asyncio import AsyncSession

from db_api.database import Accounts, db
from data.session import BaseAsyncSession
from data.config import logger, tasks_lock
from settings.settings import NUMBER_OF_ATTEMPTS, MIN_ECLIPSE_ETH_AMOUNT
from data.models import TokenAmount


class Base:
    def __init__(self, data: Accounts):
        self.data = data
        self.async_session = BaseAsyncSession(
            proxy=data.proxy, 
            verify=False, 
            user_agent=self.data.user_agent
        )
        self.version = self.data.user_agent.split('Chrome/')[1].split('.')[0]
        self.platfrom = self.data.user_agent.split(' ')[1][1:].replace(';', '')
        if self.platfrom == "Macintosh":
            self.platfrom = "MacOS"
        elif self.platfrom == "X11":
            self.platfrom = "Linux"
        self.min_eclipse_eth_amount = TokenAmount(MIN_ECLIPSE_ETH_AMOUNT, 9)

    @staticmethod
    def retry(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            for num in range(1, NUMBER_OF_ATTEMPTS + 1):
                try:
                    logger.info(f'[{self.data.id}] | {self.data.sol_address} | попытка {num}/{NUMBER_OF_ATTEMPTS}')
                    # Попробовать вызвать оригинальную функцию
                    status = await func(self, *args, **kwargs)
                    if status:
                        return True
                    else:
                        continue 
                
                except Exception as e:
                    logger.error(f"{self.data.sol_address} | Attempt {num}/{NUMBER_OF_ATTEMPTS} failed due to: {e}")
                    if num == NUMBER_OF_ATTEMPTS:
                        return 
                    await asyncio.sleep(1)  

        return wrapper

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.async_session.close()


    async def write_to_db(self):
        async with AsyncSession(db.engine) as session:
            await session.merge(self.data)
            await session.commit()
                

    async def get_token_price_from_coingecko(self, token):
        
        token_id = {
            "SOL": 'solana',
            "USDC": 'usd-coin',
            "USDT": 'tether',
            "tETH": 'ethereum'
        }

        if token in ["USDC", "USDT"]:
            return 1.0  

        url = f"https://api.coingecko.com/api/v3/simple/price?ids={token_id.get(token)}&vs_currencies=usd"

        try:
            response = await self.async_session.get(url)
            
            if response.status_code != 200:
                raise ValueError(f"Ошибка запроса: {response.status_code} - {response.text}")

            try:
                data = response.json()
            except json.JSONDecodeError:
                raise ValueError(f"Ошибка декодирования JSON: {response.text}")

            return data.get(token_id[token], {}).get('usd', None)

        except Exception as e:
            raise RuntimeError(f"Ошибка при запросе цены токена: {str(e)}") from e
        
    async def check_token_balances(self):
        """
        Проверяет баланс токенов и определяет наибольший актив по стоимости.
        """
        max_value = 0
        max_token = None
        max_balance = None

        balance_tasks = [self.sol_client.get_token_balance(self.token[token]) for token in self.swap_settings['TOKEN_TO_ETH']]
        balances = await asyncio.gather(*balance_tasks)

        price_tasks = [self.get_token_price_from_coingecko(token) for token in self.swap_settings['TOKEN_TO_ETH']]
        prices = await asyncio.gather(*price_tasks)

        for token, balance_data, price in zip(self.swap_settings['TOKEN_TO_ETH'], balances, prices):
            balance = TokenAmount(*balance_data)

            if price is not None:
                value = float(balance.Ether) * price
                logger.info(
                    f"{self.data.sol_address} | Баланс: {balance.Ether} {token}, Цена: {price} USD, Стоимость: {value} USD"
                )

                if value > max_value:
                    max_value = value
                    max_token = token
                    max_balance = balance
            else:
                logger.warning(f"Не удалось получить цену для токена {token}")

        if max_token:
            logger.info(f"Токен с наибольшей стоимостью: {max_token}, Баланс: {max_balance.Ether} {max_token}, Стоимость: {max_value} USD")
        return max_value, max_token, max_balance
