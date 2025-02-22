import asyncio
import random
import secrets

from tasks.base import Base
from clients.sol.sol_client import SolanaClient
from data.models import Networks, TokenAmount
from settings.settings import RPC_DICT, MIN_USDC_BALANCE, SLEEP_BEETWEEN_ACTIONS, PERSENT_TO_LENDING_FROM_ETH, MIX_SWAP
from data.config import logger
from data.models import ECLIPSE_TOKEN
from data.router import possible_router


class AstrolLending(Base):

    def __init__(self, data):
        super().__init__(data)
        self.sol_client = SolanaClient(self.data.sol_pk, self.data.proxy, RPC_DICT['ECLIPSE'])
        self.network = Networks.Eclipse
        self.usdc_token = ECLIPSE_TOKEN['USDC']
        self.min_usdc_balance = MIN_USDC_BALANCE

    @Base.retry
    async def start_deposit(self):

        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))

        if current_balance.Ether < self.min_eclipse_eth_amount.Ether:
            logger.error(
                f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. MIN_ECLIPSE_ETH_BALANCE: {self.min_eclipse_eth_amount.Ether} {self.network.coin_symbol}'
            )
            return True

        if not self.data.astrol_usdc_account_registed:
            logger.warning(f'[{self.data.id}] | {self.data.sol_address} аккаунт USDC не зарегистрирован... Пробую начинать регистрацию USDC аккаунта')
            status, tx_hash, astrol_acc_pk = await self.sol_client.start_initialize_astrol_acc()
            if status:
                self.data.astrol_usdc_account_registed = True
                self.data.astrol_account_pk = astrol_acc_pk
                await self.write_to_db()
                logger.success(f'[{self.data.id}] | {self.data.sol_address} успешно сделал регастрацию astrol аккаунта. Tx hash: {self.network.explorer}{tx_hash}')
                sleep_time = random.randint(SLEEP_BEETWEEN_ACTIONS[0], SLEEP_BEETWEEN_ACTIONS[1])
                logger.info(f'[{self.data.id}] | {self.data.sol_address} сон {sleep_time} секунд...')
                await asyncio.sleep(sleep_time)
            else:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог сделать регастрацию astrol аккаунта! Ошибка: {tx_hash}')
                return False

        if self.data.astrol_usdc_account_registed:
        
            usdc_balance = TokenAmount(*await self.sol_client.get_token_balance(token=self.usdc_token))

            if float(usdc_balance.Ether) < MIN_USDC_BALANCE:
                current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))
                percent_eth_to_swap = secrets.randbelow(PERSENT_TO_LENDING_FROM_ETH[1] - PERSENT_TO_LENDING_FROM_ETH[0] + 1) + PERSENT_TO_LENDING_FROM_ETH[0]
                amount_eth_to_dep = TokenAmount(int((current_balance.Wei / 100) * percent_eth_to_swap), 9, wei=True)

                if current_balance.Ether < amount_eth_to_dep.Ether + self.min_eclipse_eth_amount.Ether:
                    logger.error(
                        f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса для покупки USDC. '
                        f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. Необходимый : {amount_eth_to_dep.Ether + self.min_eclipse_eth_amount.Ether} ETH'
                    )
                    return True

                platform = random.choice(MIX_SWAP) 
                logger.info(
                    f'[{self.data.id}] | {self.data.sol_address} текущего баланса USDC недостаточно для лендинга... '
                    f'Текущий баланс: {usdc_balance.Ether} USDC. Необходимый минимальный баланс: {MIN_USDC_BALANCE} USDC. '
                    f'Пробую свапнуть {percent_eth_to_swap}% ETH на {platform} ({amount_eth_to_dep.Ether} ETH)...'
                )

                async with possible_router.get(platform)(data=self.data) as swap_platform:
                    status = await swap_platform.swap_native_to_token(token_to_swap='USDC', amount_eth_to_dep=amount_eth_to_dep)
                    if status:
                        sleep_time = random.randint(SLEEP_BEETWEEN_ACTIONS[0], SLEEP_BEETWEEN_ACTIONS[1])
                        logger.info(f'[{self.data.id}] | {self.data.sol_address} сон {sleep_time} секунд...')
                        await asyncio.sleep(sleep_time)
                        
                        usdc_balance = TokenAmount(*await self.sol_client.get_token_balance(token=self.usdc_token))
                        if float(usdc_balance.Ether) > MIN_USDC_BALANCE:
                            logger.info(f'[{self.data.id}] | {self.data.sol_address} пробую положить в лендинг {usdc_balance.Ether} USDC')

                            status, tx_hash = await self.sol_client.start_make_astrol_lending(self.data, usdc_balance)
            else:
                logger.info(f'[{self.data.id}] | {self.data.sol_address} пробую положить в лендинг {usdc_balance.Ether} USDC')
                status, tx_hash = await self.sol_client.start_make_astrol_lending(self.data, usdc_balance)

            if status:
                self.data.astrol_usdc_deposited = True
                self.data.astrol_sum_deposited = float(usdc_balance.Ether)
                await self.write_to_db()
                logger.success(f'[{self.data.id}] | {self.data.sol_address} успешно задепал в лендинг {usdc_balance.Ether} USDC. Tx hash: {self.network.explorer}{tx_hash}')
                return True
            else:
                logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог сделать депозит USDC в astrol! Ошибка: {tx_hash}')
                return False

        return False
    
    @Base.retry
    async def start_withdraw(self):

        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))

        if current_balance.Ether < self.min_eclipse_eth_amount.Ether:
            logger.error(
                f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. MIN_ECLIPSE_ETH_BALANCE: {self.min_eclipse_eth_amount.Ether} {self.network.coin_symbol}'
            )
            return True

        amount_to_withdraw = TokenAmount(self.data.astrol_sum_deposited, decimals=6)

        logger.info(f'[{self.data.id}] | {self.data.sol_address} пробую снять с лендинга {amount_to_withdraw.Ether} USDC')
        
        status, tx_hash = await self.sol_client.start_withdraw_astrol_lending(self.data, amount_to_withdraw)

        if status:
            self.data.astrol_sum_deposited = 0
            self.data.astrol_usdc_deposited = 0
            await self.write_to_db()
            logger.success(f'[{self.data.id}] | {self.data.sol_address} успешно снял {amount_to_withdraw.Ether} USDC. Tx hash: {self.network.explorer}{tx_hash}')
            return True
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог снять {amount_to_withdraw.Ether} USDC. Ошибка: {tx_hash}')
            return False

        return False