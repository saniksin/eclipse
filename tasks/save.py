from tasks import Base

import asyncio
import random
import secrets

from tasks.base import Base
from clients.sol.sol_client import SolanaClient
from data.models import Networks, TokenAmount
from settings.settings import RPC_DICT, MIN_ECLIPSE_ETH_AMOUNT, SLEEP_BEETWEEN_ACTIONS, PERSENT_TO_LENDING_FROM_ETH, MIX_SWAP
from data.config import logger
from data.models import ECLIPSE_TOKEN
from data.router import possible_router


class SaveFinance(Base):

    def __init__(self, data):
        super().__init__(data)
        self.sol_client = SolanaClient(self.data.sol_pk, self.data.proxy, RPC_DICT['ECLIPSE'])
        self.network = Networks.Eclipse
        self.eth_token = ECLIPSE_TOKEN['ETH']


    @Base.retry
    async def start_deposit(self):

        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))

        if current_balance.Ether < self.min_eclipse_eth_amount.Ether:
            logger.error(
                f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. MIN_ECLIPSE_ETH_BALANCE: {self.min_eclipse_eth_amount.Ether} {self.network.coin_symbol}'
            )
            return True
        
        current_balance = TokenAmount(*await self.sol_client.get_token_balance(native=True))
        percent_eth_to_swap = secrets.randbelow(PERSENT_TO_LENDING_FROM_ETH[1] - PERSENT_TO_LENDING_FROM_ETH[0] + 1) + PERSENT_TO_LENDING_FROM_ETH[0]
        amount_eth_to_dep = TokenAmount(int((current_balance.Wei / 100) * percent_eth_to_swap), 9, wei=True)


        if not self.data.save_finance_account_registed:
            fee_for_account_create = TokenAmount(97104, 9, wei=True)
            total_tx_cost = self.min_eclipse_eth_amount.Ether + amount_eth_to_dep.Ether + fee_for_account_create.Ether

            if current_balance.Ether <= total_tx_cost:
                logger.error(
                    f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                    f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. Необходимый баланс to deposit + MIN_ECLIPSE_ETH_BALANCE + fee_for_account_create {total_tx_cost} {self.network.coin_symbol}'
                    f''
                )
                return True
            
            logger.info(f'[{self.data.id}] | {self.data.sol_address} | пробую положить в SaveFinance {amount_eth_to_dep.Ether} ETH')
            
        else:
            fee_for_account_create = TokenAmount(117028, 9, wei=True)
            total_tx_cost = self.min_eclipse_eth_amount.Ether + amount_eth_to_dep.Ether + fee_for_account_create.Ether
            if current_balance.Ether <= total_tx_cost:
                logger.error(
                    f'[{self.data.id}] | {self.data.sol_address} | недостаточно баланса {self.network.coin_symbol}. '
                    f'Текущий баланс: {current_balance.Ether} {self.network.coin_symbol}. Необходимый баланс to deposit + MIN_ECLIPSE_ETH_BALANCE + fee_for_account_create {total_tx_cost} {self.network.coin_symbol}'
                    f''
                )
                return True
            
            logger.info(f'[{self.data.id}] | {self.data.sol_address} | пробую положить в SaveFinance {amount_eth_to_dep.Ether} ETH')

        status, tx_hash = await self.sol_client.start_deposit_eth_to_save_finance(self.data, amount_eth_to_dep)

        if status:
            self.data.save_finance_account_registed = True
            self.data.save_finance_eth_deposited = True
            self.data.save_finance_sum_deposited = float(amount_eth_to_dep.Ether)
            await self.write_to_db()
            logger.success(f'[{self.data.id}] | {self.data.sol_address} успешно задепал в лендинг SaveFinance {amount_eth_to_dep.Ether} ETH. Tx hash: {self.network.explorer}{tx_hash}')
            return True
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог сделать депозит ETH в SaveFinance! Ошибка: {tx_hash}')
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
        
        amount_to_withdraw = TokenAmount(self.data.save_finance_sum_deposited, decimals=9)

        logger.info(f'[{self.data.id}] | {self.data.sol_address} пробую снять с лендинга SaveFinance {amount_to_withdraw.Ether} ETH')
        
        status, tx_hash = await self.sol_client.start_withdraw_eth_safe_finance()

        if status:
            self.data.save_finance_sum_deposited = 0
            self.data.save_finance_eth_deposited = 0
            await self.write_to_db()
            logger.success(f'[{self.data.id}] | {self.data.sol_address} успешно снял {amount_to_withdraw.Ether} ETH с SaveFinance. Tx hash: {self.network.explorer}{tx_hash}')
            return True
        else:
            logger.error(f'[{self.data.id}] | {self.data.sol_address} не смог снять {amount_to_withdraw.Ether} ETH с SaveFinance. Ошибка: {tx_hash}')
            return False
        
        return False