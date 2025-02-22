import re
import string
import random
import json
import base64
from json import loads
from time import time
from base64 import b64decode

import asyncio
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.token.associated import get_associated_token_address
from solders.pubkey import Pubkey
from solders.message import Message, MessageV0, MessageAddressTableLookup, to_bytes_versioned
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.system_program import (
    transfer, TransferParams, 
    create_account, CreateAccountParams,
    create_account_with_seed, CreateAccountWithSeedParams
)

from solders.transaction import Transaction, VersionedTransaction
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts, TokenAccountOpts
from solders.signature import Signature
from solders.instruction import AccountMeta, Instruction
from solana.rpc.core import RPCException
from spl.token.instructions import create_associated_token_account, close_account, CloseAccountParams

from data.models import ECLIPSE_TOKEN, LOCKUP_TABLE_ACCOUNT, Networks
from data.config import logger
from data.eth_convertor import TokenAmount
from settings.settings import NUMBER_OF_ATTEMPTS, TURBO_TAP_AMOUNT_TO_DEPOSIT
from db_api.database import Accounts


class SolanaClient():

    def __init__(self, sol_pk: str, proxy: str, rpc: str):
        self.private_key = sol_pk
        self.rpc = rpc
        self.client = AsyncClient(rpc, proxy=proxy)
        self.account = Keypair.from_base58_string(sol_pk)
        self.address = self.account.pubkey()
        self.eclipse_usdc = ECLIPSE_TOKEN['USDC']

    async def get_token_balance(self, token: dict | str = "ETH", native=False, pubkey=None):

        for _ in range(1, 1000000):
            
            try:
                if native:
                    try:
                        if not pubkey:
                            pubkey = self.address

                        decimals = 9
                        token_balance = (await self.client.get_account_info(pubkey)).value.lamports
                        return token_balance / 10 ** decimals, decimals
                    except AttributeError:
                        return 0, 9
                
                else:
                    try:
                        associated_token = get_associated_token_address(
                            wallet_address=self.address, 
                            token_mint_address=Pubkey.from_string(token['token_address']),    
                            token_program_id=Pubkey.from_string(token['token_program'])            
                        )

                        token_info = await self.client.get_token_account_balance(associated_token)
                        token_balance, decimals = int(token_info.value.amount), token_info.value.decimals
                        
                        return token_balance / 10 ** decimals, decimals
                    except (TypeError, AttributeError):
                        return [0]
            except Exception as e:
                print(e)
                continue

    def get_client_associated_token_address(self, token):
        return get_associated_token_address(
            wallet_address=self.address, 
            token_mint_address=Pubkey.from_string(token['token_address']),    
            token_program_id=Pubkey.from_string(token['token_program'])            
        )
                
    def _get_error_reason(self, logs: list):
        return list([
            log.removeprefix("Program log: Error: ")
            for log in logs
            if (
                log.startswith("Program log: Error: ") or
                "compute units" in log
            )
            ] + [""]
        )[0]

    async def get_tx_status(self, signature: Signature, timeout_minutes: int = 2):
        """
        Получает статус транзакции по ее подписи.

        :param signature: Подпись транзакции (Signature).
        :param timeout_minutes: Время ожидания завершения транзакции в минутах (по умолчанию: 1).
        :return: Словарь с результатом выполнения транзакции.
        """
        started = time()
        timeout_seconds = int(timeout_minutes * 60)

        while True:
            tx = await self.client.get_transaction(signature, max_supported_transaction_version=0)
            if tx.value:
                break  # Если транзакция найдена, выходим из цикла

            if time() - started > timeout_seconds:
                logger.warning(f"{self.address} | transaction {signature} not confirmed within {timeout_minutes} minutes.")
                return {"success": False, "msg": None} 

            await asyncio.sleep(1)  

        # Получение метаданных и преобразование в JSON
        tx_result = loads(tx.value.transaction.meta.to_json())
        logs = tx_result.get("logMessages", [])
        status = tx_result.get("err") is None and "Ok" in tx_result.get("status", "")

        # Анализ логов для определения причины ошибки
        reason = self._get_error_reason(logs)
        return {"success": status, "msg": reason}


    @staticmethod
    def extract_indices_from_instructions(instruction_objects, pubkey):
        """
        Извлекает индексы используемых публичных ключей из инструкций.

        :param instruction_objects: Список объектов TransactionInstruction.
        :param lockup_table_account: Словарь LOCKUP_TABLE_ACCOUNT.
        :return: Кортеж из двух списков: (readonly_indices, writable_indices).
        """
        pubkey_to_index = LOCKUP_TABLE_ACCOUNT.get(str(pubkey), {})
        
        writable_indices = []
        readonly_indices = []

        for instruction in instruction_objects:
            for account in instruction.accounts:
                pubkey_str = str(account.pubkey)
                if pubkey_str in pubkey_to_index:
                    index = pubkey_to_index[pubkey_str]
                    if account.is_writable:
                        if index not in writable_indices:
                            writable_indices.append(index)
                    else:
                        if index not in readonly_indices:
                            readonly_indices.append(index)
        
        return readonly_indices, writable_indices
    
    @staticmethod
    def create_message_address_table_lookup(instruction_objects, lockup_table_addresses):
        """
        Создаёт объект MessageAddressTableLookup.

        :param lockup_table_address: Строка адреса таблицы адресов.
        :param readonly_indices: Список индексов для readonly адресов.
        :param writable_indices: Список индексов для writable адресов.
        :return: Объект MessageAddressTableLookup.
        """

        answer = []
        for pubkey in lockup_table_addresses:
            readonly_indices, writable_indices = SolanaClient.extract_indices_from_instructions(instruction_objects, pubkey)
            answer.append(
                MessageAddressTableLookup(
                    account_key=pubkey,
                    writable_indexes=bytes(writable_indices),
                    readonly_indexes=bytes(readonly_indices)
                )   
                )
        return answer
    

    async def swap_tx_orca(self, instructions, address_table_lookups, signers):
        
        # Создаём Keypair для подписи
        all_signers = [Keypair.from_bytes(bytes(acc)) for acc in signers]

        # Преобразуем адреса таблиц в Pubkey объекты
        table_pubkeys = [Pubkey.from_bytes(bytes(acc)) for acc in address_table_lookups]


        # 1. Установка лимита вычислений
        compute_budget_program_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        #data = random.randint(199123, 230809)
        data = random.randint(254000, 270000)
        set_compute_unit_limit_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([2]) + (data).to_bytes(4, "little")
        )

        # 2. Установка цены за вычислительную единицу
        #data = random.randint(4900, 5100)
        data = random.randint(3700, 4300)
        set_compute_unit_price_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([3]) + (data).to_bytes(8, "little")  
        )

        # Создание инструкций
        instruction_objects = [
            Instruction(
                program_id=Pubkey.from_bytes(bytes(inst["programId"])),
                accounts=[
                    AccountMeta(
                        pubkey=Pubkey.from_bytes(bytes(acc["pubkey"])),
                        is_signer=acc["isSigner"],
                        is_writable=acc["isWritable"]
                    ) for acc in inst["accounts"]
                ],
                data=bytes(inst["data"])
            ) for inst in instructions
        ]

        instruction_objects = [
            set_compute_unit_limit_instruction,
            set_compute_unit_price_instruction,
            *instruction_objects
        ]

        prepepare_table_lookups_v0 = []
        for item in table_pubkeys:
            all_addresses = LOCKUP_TABLE_ACCOUNT.get(str(item), {}).keys()
            if all_addresses:
                all_addresses_pubkeys = [Pubkey.from_string(key) for key in all_addresses]
                prepepare_table_lookups_v0.append(AddressLookupTableAccount(item, all_addresses_pubkeys))
            else:
                return False, f'{str(item)} нету в LOCKUP_TABLE_ACCOUNT! Нужно добавить'

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=instruction_objects,
            address_lookup_table_accounts=prepepare_table_lookups_v0,
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account, *all_signers]
        )

        sim_res = await self.client.simulate_transaction(tx)
        #print(sim_res)

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except Exception as e:
            return False, e
        

    async def get_register_tap_instr(self, keypair, second_acc_key, amount_to_deposit, only_transfer=False):
        # 1. Инструкция Unknown, вызывающая CreateAccount
        unknown_instruction = Instruction(
            program_id=Pubkey.from_string('turboe9kMc3mSR8BosPkVzoHUfn5RVNzZhkrT2hdGxN'),  
            accounts=[
                AccountMeta(pubkey=keypair, is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=second_acc_key.pubkey(), is_signer=True, is_writable=True),
            ],
            data=bytes.fromhex("46b09eea38df8354"), 
        )

        # 2. Создание второй инструкции (Transfer)
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=self.address,   
                to_pubkey=second_acc_key.pubkey(), 
                lamports=amount_to_deposit       
            )
        )
        
        if only_transfer:
            message = Message(
                instructions=[
                    transfer_instruction
                ],
                payer=self.address
            ) 
            tx = Transaction(
                from_keypairs=[
                    self.account,
                ],
                message=message,
                recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
            )
        else:
            message = Message(
                instructions=[
                    unknown_instruction,
                    transfer_instruction
                ],
                payer=self.address
            ) 
            tx = Transaction(
                from_keypairs=[
                    self.account,
                    second_acc_key
                ],
                message=message,
                recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
            )

        return tx

    def get_solana_pk(self):
        return Keypair().to_json()
    
    async def start_register_tap_acc(self, data: Accounts): 
        second_acc_key = Keypair.from_bytes(bytes(json.loads(data.turbo_tap_pk)))

        second_acc_balance = TokenAmount(*await self.get_token_balance(native=True, pubkey=second_acc_key.pubkey()))
        
        amount_to_deposit = TURBO_TAP_AMOUNT_TO_DEPOSIT + 8750 if second_acc_balance.Wei != 8750 else TURBO_TAP_AMOUNT_TO_DEPOSIT
        tx = await self.get_register_tap_instr(
            Keypair().pubkey(),
            second_acc_key,
            amount_to_deposit
        )

        # Отправка транзакции
        try:
            try:
                tx_hash_ = await self.client.send_raw_transaction(
                    txn=bytes(tx),
                    opts=TxOpts(
                        skip_confirmation=True,
                        skip_preflight=False,
                        preflight_commitment=Confirmed,
                    )
                )
            except RPCException as e:
                match = re.search(r'Program log: Right:",\s"Program log: ([a-zA-Z0-9]+)"', str(e))

                if match:
                    extracted_address = match.group(1)

                    if second_acc_balance.Wei > 8750:
                        return 'already used', extracted_address, 'Игровой аккаунт уже был пополнен либо использован!'

                    elif second_acc_balance.Wei == 8750:
                        tx = await self.get_register_tap_instr(
                            Pubkey.from_string(extracted_address),
                            second_acc_key,
                            amount_to_deposit,
                            only_transfer=True
                        )
                    else:
                        tx = await self.get_register_tap_instr(
                            Pubkey.from_string(extracted_address),
                            second_acc_key,
                            amount_to_deposit
                        )

                    tx_hash_ = await self.client.send_raw_transaction(
                        txn=bytes(tx),
                        opts=TxOpts(
                            skip_confirmation=True,
                            skip_preflight=False,
                            preflight_commitment=Confirmed,
                        )
                    )
                    tx_hash = tx_hash_.value
                else:
                    return 'error', '', 'extracted_address not found'

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                if amount_to_deposit == TURBO_TAP_AMOUNT_TO_DEPOSIT + 8750:
                    return 'success', extracted_address, tx_hash
                else:
                    return 'depositold', extracted_address, tx_hash
            else:
                return 'tx_fail', extracted_address, tx_hash
            
        except Exception as e:
            return 'error', '', e

    @staticmethod
    def generate_random_instruction(base):
        # Генерируем случайные два символа: цифры от 0 до 9 и буквы от 'a' до 'f'
        suffix = ''.join(random.choices(string.hexdigits.lower()[:16], k=2))
        return base + suffix
    
    @staticmethod
    def generate_random_new_instruction(base):
        # Генерируем случайное 32-битное число и переводим в 8-символьный хекс
        suffix = f"{random.randint(0, 4294967295):08x}"
        return base + suffix
    
    async def start_tap(self, data):
    
        game_acc_pk = Keypair.from_bytes(bytes(json.loads(data.turbo_tap_pk)))
        game_acc_pubkey = Pubkey.from_string(data.turbo_tap_pubkey)

        sol_balance = TokenAmount(*await self.get_token_balance(native=True, pubkey=game_acc_pk.pubkey()))

        extracted_address = Pubkey.from_string('HwXj2vcHCiaoUVNrp9KnWWAF6yGtx8bTmbUThv5u53R5')
        while int(sol_balance.Wei) > 8750:
            try:
                # Program ID для ComputeBudget
                compute_budget_program_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")

                # Данные инструкции
                discriminator = bytes([2])  
                units = (60000).to_bytes(4, "little") 

                # Создание инструкции
                set_compute_unit_limit_instruction = Instruction(
                    program_id=compute_budget_program_id,
                    accounts=[],  
                    data=discriminator + units  #
                )

                unknown_instruction = Instruction(
                    program_id=Pubkey.from_string('turboe9kMc3mSR8BosPkVzoHUfn5RVNzZhkrT2hdGxN'),  
                    accounts=[
                        AccountMeta(pubkey=game_acc_pubkey, is_signer=False, is_writable=False),
                        AccountMeta(pubkey=extracted_address, is_signer=False, is_writable=True),
                        AccountMeta(pubkey=Pubkey.from_string('9FXCusMeR26k1LkDixLF2dw1AnBX8SsB2cspSSi3BcKE'), is_signer=False, is_writable=False),
                        AccountMeta(pubkey=game_acc_pk.pubkey(), is_signer=True, is_writable=True),
                        AccountMeta(pubkey=Pubkey.from_string('Sysvar1nstructions1111111111111111111111111'), is_signer=False, is_writable=False),
                    ],
                    #data=bytes.fromhex(self.generate_random_instruction('0b93b3b291762dba')), 
                    data=bytes.fromhex(self.generate_random_new_instruction('76bc1772dbfb4252')), 
                )

                message = Message(
                    instructions=[
                        set_compute_unit_limit_instruction,
                        unknown_instruction,
                    ],
                    payer=game_acc_pk.pubkey()
                ) 
                
                tx = Transaction(
                    from_keypairs=[
                        game_acc_pk
                    ],
                    message=message,
                    recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
                )

                try:
                    tx_hash_ = await self.client.send_raw_transaction(
                        txn=bytes(tx),
                        opts=TxOpts(
                            skip_confirmation=True,
                            skip_preflight=False,
                            preflight_commitment=Confirmed,
                        )
                    )
                    
                except RPCException as e:
                    #print(e)

                    match = re.search(r'Program log: Right:",\s"Program log: ([a-zA-Z0-9]+)"', str(e))

                    if match:
                        extracted_address = Pubkey.from_string(match.group(1))
                        #print(extracted_address)
                        continue

                tx_hash = tx_hash_.value

                # Проверка статуса транзакции
                # tx_status = await self.get_tx_status(signature=tx_hash)

                logger.success(f'{[data.id]} | {data.sol_address} | Баланс {sol_balance.Ether} ETH | успешно отправил tap транзакцию! Tx hash: {Networks.Eclipse.explorer}{tx_hash}')

                # if tx_status["success"]:
                #     logger.success(f'{data.sol_address} | Баланс {sol_balance.Ether} ETH | успешно отправил tap транзакцию! Tx hash: {Networks.Eclipse.explorer}{tx_hash}')
                # else:
                #     logger.error(f'{data.sol_address} | Баланс {sol_balance.Ether} ETH | не смог отправить tap транзакцию! Tx hash: {Networks.Eclipse.explorer}{tx_hash}')
                
                sol_balance = TokenAmount(*await self.get_token_balance(native=True, pubkey=game_acc_pk.pubkey()))

            except Exception as e:
                logger.error(f'{data.sol_address} | неизвестная ошибка: {e}')
            
        return True
    
    @staticmethod
    def get_router_list():
        transfer_to = [
            'Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY',
            '3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT',
            '96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5'
        ]

        return random.choice(transfer_to)
        
    
    async def start_initialize_astrol_acc(self):
        astol_acc = Keypair()

        # 1. Создание первой инструкции (Transfer)
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=self.address,   
                to_pubkey=Pubkey.from_string(self.get_router_list()), 
                lamports=10000       
            )
        )

        # 2. Создание второй инструкции (Astrolend acc initialize)
        astrolend_acc_initialize = Instruction(
            program_id=Pubkey.from_string('Astro1oWvtB7cBTwi3efLMFB47WXx7DJDQeoxi235kA'),  
            accounts=[
                AccountMeta(pubkey=Pubkey.from_string('8GzZHDKts3oHeL91h4fYjbjaAcUicBb8NB6ZTLTHvYr6'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=astol_acc.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False),
            ],
            data=bytes.fromhex("3edc10f0a7ec486b"), 
        )

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=[
                transfer_instruction,
                astrolend_acc_initialize
            ],
            address_lookup_table_accounts=[],
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account, astol_acc]
        )

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash, str(astol_acc)
            else:
                return False, tx_hash, str(astol_acc)
            
        except Exception as e:
            return False, e, str(astol_acc)
        
    async def start_make_astrol_lending(self, data: Accounts, deposit_amount: TokenAmount):

        try:
            wallet_pubkey = Pubkey.from_string(data.astrol_account_pk)
        except ValueError:
            wallet_pubkey = Keypair.from_base58_string(data.astrol_account_pk).pubkey()
        
        # 1. Установка лимита вычислений
        compute_budget_program_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        budge_number = random.randint(54000, 56000)
        set_compute_unit_limit_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([2]) + (budge_number).to_bytes(4, "little")
        )

        # 2. Создание первой инструкции (Transfer)
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=self.address,   
                to_pubkey=Pubkey.from_string(self.get_router_list()), 
                lamports=10000       
            )
        )

        # 3. Set Compute Unit Price
        set_second_compute_unit_limit_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([3]) + (1).to_bytes(8, "little")
        )
        
        # 4. Astrolend: Lending_account_deposit
        associated_token = get_associated_token_address(
            wallet_address=self.address, 
            token_mint_address=Pubkey.from_string(self.eclipse_usdc['token_address']),    
            token_program_id=Pubkey.from_string(self.eclipse_usdc['token_program'])            
        )
        
        # data
        header = bytes.fromhex("ab5eeb675240d48c")
        value = deposit_amount.Wei
        value_data = value.to_bytes(8, "little")
        instruction_data = header + value_data

        lending_account_deposit = Instruction(
            program_id=Pubkey.from_string('Astro1oWvtB7cBTwi3efLMFB47WXx7DJDQeoxi235kA'),  
            accounts=[
                AccountMeta(pubkey=Pubkey.from_string('8GzZHDKts3oHeL91h4fYjbjaAcUicBb8NB6ZTLTHvYr6'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=wallet_pubkey, is_signer=False, is_writable=True),                
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('7NeDyW6MA7zLdTWDbctFoXfJ6vSQX7YvtBh7EbdXqDi9'), is_signer=False, is_writable=True),
                AccountMeta(pubkey=associated_token, is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('2NMiz7J9VZMqjqBRx2VE1VmszoMRdF32gA9utdiTAeGq'), is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=Pubkey.from_string('AKEWE7Bgh87GPp171b4cJPSSZfmZwQ3KaqYqXoKLNAEE'), is_signer=False, is_writable=False),
            ],
            data=instruction_data
        )

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=[
                set_compute_unit_limit_instruction,
                transfer_instruction,
                set_second_compute_unit_limit_instruction,
                lending_account_deposit
            ],
            address_lookup_table_accounts=[],
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account]
        )

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except Exception as e:
            return False, e
        
    async def start_withdraw_astrol_lending(self, data: Accounts, deposit_amount: TokenAmount):
        
        # 1. Установка лимита вычислений
        compute_budget_program_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
        budge_number = random.randint(67000, 72000)
        set_compute_unit_limit_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([2]) + (budge_number).to_bytes(4, "little")
        )

        # 2. Создание инструкции (Transfer)
        transfer_instruction = transfer(
            TransferParams(
                from_pubkey=self.address,   
                to_pubkey=Pubkey.from_string(self.get_router_list()), 
                lamports=10000       
            )
        )

        # 3. Set Compute Unit Price
        set_second_compute_unit_limit_instruction = Instruction(
            program_id=compute_budget_program_id,
            accounts=[],
            data=bytes([3]) + (1).to_bytes(8, "little")
        )

        # 4. CreateIdempotent
        associated_token = get_associated_token_address(
            wallet_address=self.address, 
            token_mint_address=Pubkey.from_string(self.eclipse_usdc['token_address']),    
            token_program_id=Pubkey.from_string(self.eclipse_usdc['token_program'])            
        )

        create_idempotent_instruction = Instruction(
            program_id=Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),  
            accounts=[
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=associated_token, is_signer=False, is_writable=True), 
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),       
                AccountMeta(pubkey=Pubkey.from_string('AKEWE7Bgh87GPp171b4cJPSSZfmZwQ3KaqYqXoKLNAEE'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=Pubkey.from_string('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'), is_signer=False, is_writable=False),
            ],
            data=bytes.fromhex('01')
        )

        # 5. Lending withdraw tx
        try:
            wallet_pubkey = Pubkey.from_string(data.astrol_account_pk)
        except ValueError:
            wallet_pubkey = Keypair.from_base58_string(data.astrol_account_pk).pubkey()

        # tx data
        header = bytes.fromhex("24484a13d2d2c0c0")
        value = deposit_amount.Wei
        value_data = value.to_bytes(8, "little")
        end = bytes.fromhex("0101")

        # Полная инструкция
        instruction_data = header + value_data + end

        lending_account_withdraw_instruction = Instruction(
            program_id=Pubkey.from_string('Astro1oWvtB7cBTwi3efLMFB47WXx7DJDQeoxi235kA'),  
            accounts=[
                AccountMeta(pubkey=Pubkey.from_string('8GzZHDKts3oHeL91h4fYjbjaAcUicBb8NB6ZTLTHvYr6'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=wallet_pubkey, is_signer=False, is_writable=True),
                AccountMeta(pubkey=self.address, is_signer=True, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('7NeDyW6MA7zLdTWDbctFoXfJ6vSQX7YvtBh7EbdXqDi9'), is_signer=False, is_writable=True),
                AccountMeta(pubkey=associated_token, is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('JBUYTVaQAvp61GKnbgooEEzyTsevG1x5fYDnGoDD2soT'), is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('2NMiz7J9VZMqjqBRx2VE1VmszoMRdF32gA9utdiTAeGq'), is_signer=False, is_writable=True),
                AccountMeta(pubkey=Pubkey.from_string('TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'), is_signer=False, is_writable=False),
                AccountMeta(pubkey=Pubkey.from_string('AKEWE7Bgh87GPp171b4cJPSSZfmZwQ3KaqYqXoKLNAEE'), is_signer=False, is_writable=False), 
            ],
            data=instruction_data
        )

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=[
                set_compute_unit_limit_instruction,
                transfer_instruction,
                set_second_compute_unit_limit_instruction,
                create_idempotent_instruction,
                lending_account_withdraw_instruction
            ],
            address_lookup_table_accounts=[],
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account]
        )

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except Exception as e:
            return False, e
        
    async def tx_via_ready_data(self, data):
        message = Transaction.from_bytes(b64decode(data)).message
        completed_signatures = [
            self.account.sign_message(to_bytes_versioned(message))
        ]
        tx = Transaction.populate(message, completed_signatures)
       
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except Exception as e:
            return False, e
        
    async def tx_v0_via_ready_data(self, data):
        tx = VersionedTransaction.from_bytes(b64decode(data))
        tx_signatures = tx.signatures

        completed_signatures = [
            self.account.sign_message(to_bytes_versioned(tx.message))
        ]

        if str(tx_signatures[0]) == "1111111111111111111111111111111111111111111111111111111111111111":
            tx_signatures[0] = completed_signatures[0]

        tx = VersionedTransaction.populate(tx.message, tx_signatures)
       
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash

        except Exception as e:
            return False, e
        
    async def start_deposit_eth_to_save_finance(self, data: Accounts, amount: TokenAmount, exception_counter = 0):
        
        all_instruction = []

        # 1. Set Compute Unit Price
        set_compute_unit_price_instruction = Instruction(
            program_id=Pubkey.from_string('ComputeBudget111111111111111111111111111111'),
            accounts=[],
            data=bytes([3]) + (0).to_bytes(8, "little")
        )
        all_instruction.append(set_compute_unit_price_instruction)

        # 2. Set Compute Unit Limit
        set_compute_unit_limit_instruction = Instruction(
            program_id=Pubkey.from_string('ComputeBudget111111111111111111111111111111'),
            accounts=[],
            data=bytes([2]) + (1_000_000).to_bytes(4, "little")
        )
        all_instruction.append(set_compute_unit_limit_instruction)
        
        if not data.save_finance_account_registed and exception_counter == 0:
            # 3. Transfer 
            associated_eth_token_address = get_associated_token_address(
                self.address,
                Pubkey.from_string('So11111111111111111111111111111111111111112'), 
                Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')  
            )
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.address,   
                    to_pubkey=associated_eth_token_address, 
                    lamports=amount.Wei 
                )
            )
            all_instruction.append(transfer_instruction)

            # 4. SyncNative
            sync_native_instruction = Instruction(
                program_id=Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
                accounts=[
                    AccountMeta(
                        associated_eth_token_address, is_signer=False, is_writable=True
                    )
                ],
                data=bytes.fromhex('11')
            )
            all_instruction.append(sync_native_instruction)
        elif not data.save_finance_account_registed and exception_counter == 1:
            associated_eth_token_address = get_associated_token_address(
                self.address,
                Pubkey.from_string('So11111111111111111111111111111111111111112'), 
                Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')  
            )
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.address,   
                    to_pubkey=associated_eth_token_address, 
                    lamports=amount.Wei + 19924 
                )
            )
            all_instruction.append(transfer_instruction)

            # 4. Create Associated Token Account Program 
            create_associated_token_account_instruction = Instruction(
                program_id=Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),
                accounts=[

                    # 1
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 2
                    AccountMeta(
                        associated_eth_token_address, is_signer=False, is_writable=True
                    ),

                    # 3
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 4
                    AccountMeta(
                        Pubkey.from_string('So11111111111111111111111111111111111111112'), is_signer=False, is_writable=False
                    ),
                    
                    # 5
                    AccountMeta(
                        Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False
                    ),

                    # 6
                    AccountMeta(
                        Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                    )     

                ],
                data=bytes([0])
            )
            all_instruction.append(create_associated_token_account_instruction)
        else:
            # 3. Transfer 
            associated_eth_token_address = get_associated_token_address(
                self.address,
                Pubkey.from_string('So11111111111111111111111111111111111111112'), 
                Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')  
            )
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.address,   
                    to_pubkey=associated_eth_token_address, 
                    lamports=amount.Wei + 19924 
                )
            )
            all_instruction.append(transfer_instruction)

            # 4. Create Associated Token Account Program 
            create_associated_token_account_instruction = Instruction(
                program_id=Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),
                accounts=[

                    # 1
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 2
                    AccountMeta(
                        associated_eth_token_address, is_signer=False, is_writable=True
                    ),

                    # 3
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 4
                    AccountMeta(
                        Pubkey.from_string('So11111111111111111111111111111111111111112'), is_signer=False, is_writable=False
                    ),
                    
                    # 5
                    AccountMeta(
                        Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False
                    ),

                    # 6
                    AccountMeta(
                        Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                    )     

                ],
                data=bytes([0])
            )
            all_instruction.append(create_associated_token_account_instruction)

        seed = "2gEGvFXGjuhBGQYGLnKVbrCpW4uKFtKh" 
        program_id = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo") 
        expected_pubkey = Pubkey.create_with_seed(self.address, seed, program_id)

        if not data.save_finance_account_registed:
            # 5. Create Account With Seed
            create_account_with_seed_instruction = create_account_with_seed(
                CreateAccountWithSeedParams(
                    from_pubkey=self.address,
                    to_pubkey=expected_pubkey,
                    base=self.address,
                    seed=seed,
                    lamports=97104,
                    space=1300,
                    owner=program_id, 
                )
            )

            final_create_account_with_seed_instruction = Instruction(
                program_id=Pubkey.from_string('11111111111111111111111111111111'),
                accounts=[
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),
                    AccountMeta(
                        expected_pubkey, is_signer=False, is_writable=True
                    ),
                ],
                data=create_account_with_seed_instruction.data
            )
            all_instruction.append(final_create_account_with_seed_instruction)


            # 6. Init Obligation 
            init_obligation_instruction = Instruction(
                program_id=Pubkey.from_string('So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo'),
                accounts=[
                    AccountMeta(expected_pubkey, is_signer=False, is_writable=True),
                    AccountMeta(Pubkey.from_string('2gEGvFXGjuhBGQYGLnKVbrCpW4uKFtKhK7CevWdxMNjA'), is_signer=False, is_writable=True),
                    AccountMeta(self.address, is_signer=True, is_writable=True),
                    AccountMeta(Pubkey.from_string('SysvarRent111111111111111111111111111111111'), is_signer=False, is_writable=False),
                    AccountMeta(Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False)     
                ],
                data=bytes.fromhex('06')
            )
            all_instruction.append(init_obligation_instruction)

        # 7. Create Associated Token Account Program 
        associated_spl_token_address = get_associated_token_address(
            self.address,
            Pubkey.from_string('AbefESHCRKZKQbdcAD8qes4EjzQfzMN1KkCCMsz7TogL'), #SPL
            Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')   #TokenProgram
        )

        if not data.save_finance_account_registed:

            create_second_associated_token_account_instruction = Instruction(
                program_id=Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),
                accounts=[
                    # 1
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 2
                    AccountMeta(
                        associated_spl_token_address, is_signer=False, is_writable=True
                    ),

                    # 3
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 4
                    AccountMeta(
                        Pubkey.from_string('AbefESHCRKZKQbdcAD8qes4EjzQfzMN1KkCCMsz7TogL'), is_signer=False, is_writable=True
                    ),
                    
                    # 5
                    AccountMeta(
                        Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False
                    ),

                    # 6
                    AccountMeta(
                        Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                    )     

                ],
                data=bytes([0])
            )
            all_instruction.append(create_second_associated_token_account_instruction)

        # 8. Deposit reserve liquidity and obligation collateral
        header = bytes.fromhex("0e")
        value = amount.Wei
        value_data = value.to_bytes(8, "little")
        tx_data = header + value_data

        deposit_reserve_liquidity_and_obligation_collateral_instruction = Instruction(
            program_id=Pubkey.from_string('So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo'),
            accounts=[
                # 1
                AccountMeta(
                    associated_eth_token_address, is_signer=False, is_writable=True
                ), 

                # 2
                AccountMeta(
                    associated_spl_token_address, is_signer=False, is_writable=True
                ),

                # 3
                AccountMeta(
                    Pubkey.from_string('8LU4ULP6DLTYKRthjT5FkJ7oCFM1tPLm9TEQ2BQAnfGb'), is_signer=False, is_writable=True
                ),

                # 4
                AccountMeta(
                    Pubkey.from_string('29w3f87B9gAkLY3m9rTsob67gvMbg58XsBCTTugMBgfN'), is_signer=False, is_writable=True
                ),

                # 5
                AccountMeta(
                    Pubkey.from_string('AbefESHCRKZKQbdcAD8qes4EjzQfzMN1KkCCMsz7TogL'), is_signer=False, is_writable=True
                ),

                # 6
                AccountMeta(
                    Pubkey.from_string('2gEGvFXGjuhBGQYGLnKVbrCpW4uKFtKhK7CevWdxMNjA'), is_signer=False, is_writable=True
                ),

                # 7
                AccountMeta(
                    Pubkey.from_string('5Gk1kTdDqqacmA2UF3UbNhM7eEhVFvF3p8nd9p3HbXxk'), is_signer=False, is_writable=False
                ),

                # 8
                AccountMeta(
                    Pubkey.from_string('Gwa9T34jqDfPm6RhbDqJg7rM784ZMN1hZWb7BJEF5WdK'), is_signer=False, is_writable=True
                ),

                # 9
                AccountMeta(
                    expected_pubkey, is_signer=False, is_writable=True
                ),

                # 10
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),

                # 11
                AccountMeta(
                    Pubkey.from_string('42amVS4KgzR9rA28tkVYqVXjq9Qa8dcZQMbH5EYFX6XC'), is_signer=False, is_writable=False
                ),

                # 12
                AccountMeta(
                    Pubkey.from_string('nu11111111111111111111111111111111111111111'), is_signer=False, is_writable=False
                ),

                # 13
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),

                # 14
                AccountMeta(
                    Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                )
            ],
            data=tx_data
        )
        all_instruction.append(deposit_reserve_liquidity_and_obligation_collateral_instruction)

        if data.save_finance_account_registed or (not data.save_finance_account_registed and exception_counter == 1):
            # 9. Close Account Instruction
            close_account_instruction = Instruction(
                program_id=Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
                accounts=[
                    AccountMeta(
                        associated_eth_token_address, is_signer=False, is_writable=True
                    ),
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),
                ],
                data=bytes.fromhex('09')
            )
            all_instruction.append(close_account_instruction)

        #print(len(all_instruction))

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=[
                *all_instruction
            ],
            address_lookup_table_accounts=[],
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account]
        )

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except RPCException as e:

            exception_value = {
                0: 'sync tx and dep not registred',
                1: 'create and pay fee not registred',
                2: 'registred acc tx problem'
            }

            if exception_counter > 2:
                return False, e

            if exception_counter > 0:
                logger.warning(f'[{data.id}] | {data.sol_address} попытка №{exception_counter} положить средства в savefinance. Ошибка: {exception_value[exception_counter]}')

            if exception_counter > 1:
                data.save_finance_account_registed = True
            return await self.start_deposit_eth_to_save_finance(data, amount, exception_counter + 1)

        except Exception as e:
            return False, e

    async def start_withdraw_eth_safe_finance(self, exception_counter = 0):
        all_instruction = []

        # 1. Set Compute Unit Price
        set_compute_unit_price_instruction = Instruction(
            program_id=Pubkey.from_string('ComputeBudget111111111111111111111111111111'),
            accounts=[],
            data=bytes([3]) + (0).to_bytes(8, "little")
        )
        all_instruction.append(set_compute_unit_price_instruction)

        # 2. Set Compute Unit Limit
        set_compute_unit_limit_instruction = Instruction(
            program_id=Pubkey.from_string('ComputeBudget111111111111111111111111111111'),
            accounts=[],
            data=bytes([2]) + (1_000_000).to_bytes(4, "little")
        )
        all_instruction.append(set_compute_unit_limit_instruction)

        if exception_counter == 0:
            # 3. Transfer 
            associated_eth_token_address = get_associated_token_address(
                self.address,
                Pubkey.from_string('So11111111111111111111111111111111111111112'), 
                Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')  
            )
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.address,   
                    to_pubkey=associated_eth_token_address, 
                    lamports=0 
                )
            )
            all_instruction.append(transfer_instruction)
        else:
            # 3. Transfer 
            associated_eth_token_address = get_associated_token_address(
                self.address,
                Pubkey.from_string('So11111111111111111111111111111111111111112'), 
                Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')  
            )
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.address,   
                    to_pubkey=associated_eth_token_address, 
                    lamports=19924 
                )
            )
            all_instruction.append(transfer_instruction)

            # 4. Create Associated Token Account Program 
            create_associated_token_account_instruction = Instruction(
                program_id=Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'),
                accounts=[

                    # 1
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 2
                    AccountMeta(
                        associated_eth_token_address, is_signer=False, is_writable=True
                    ),

                    # 3
                    AccountMeta(
                        self.address, is_signer=True, is_writable=True
                    ),

                    # 4
                    AccountMeta(
                        Pubkey.from_string('So11111111111111111111111111111111111111112'), is_signer=False, is_writable=False
                    ),
                    
                    # 5
                    AccountMeta(
                        Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False
                    ),

                    # 6
                    AccountMeta(
                        Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                    )     

                ],
                data=bytes([0])
            )
            all_instruction.append(create_associated_token_account_instruction)

        # 5. Solend RefreshReserve
        refresh_reserve_instruction = Instruction(
            program_id=Pubkey.from_string('So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo'),
            accounts=[
                AccountMeta(
                    Pubkey.from_string('8LU4ULP6DLTYKRthjT5FkJ7oCFM1tPLm9TEQ2BQAnfGb'), is_signer=False, is_writable=True
                ),
                 AccountMeta(
                    Pubkey.from_string('42amVS4KgzR9rA28tkVYqVXjq9Qa8dcZQMbH5EYFX6XC'), is_signer=False, is_writable=False
                ),
                AccountMeta(
                    Pubkey.from_string('nu11111111111111111111111111111111111111111'), is_signer=False, is_writable=False
                ),
                AccountMeta(
                    pubkey=Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False
                ),
            ],
            data=bytes.fromhex('03')
        )
        all_instruction.append(refresh_reserve_instruction)

        # 6. Solend RefreshObligation
        seed = "2gEGvFXGjuhBGQYGLnKVbrCpW4uKFtKh" 
        program_id = Pubkey.from_string("So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo") 
        expected_pubkey = Pubkey.create_with_seed(self.address, seed, program_id)

        refresh_obligation_instruction = Instruction(
            program_id=Pubkey.from_string('So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo'),
            accounts=[
                AccountMeta(
                    expected_pubkey, is_signer=False, is_writable=False
                ),
                AccountMeta(
                    Pubkey.from_string('8LU4ULP6DLTYKRthjT5FkJ7oCFM1tPLm9TEQ2BQAnfGb'), is_signer=False, is_writable=True
                ),
            ],
            data=bytes.fromhex('07')
        )
        all_instruction.append(refresh_obligation_instruction)

        # 7. Solend: WithdrawObligationCollateralAndRedeemReserveCollateral
        associated_spl_token_address = get_associated_token_address(
            self.address,
            Pubkey.from_string('AbefESHCRKZKQbdcAD8qes4EjzQfzMN1KkCCMsz7TogL'), #SPL
            Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')   #TokenProgram
        )

        withdraw_obligation_collateral_and_redeem_reserve_collateral_instruction = Instruction(
            program_id=Pubkey.from_string('So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo'),
            accounts=[
                # 1
                AccountMeta(
                    Pubkey.from_string('Gwa9T34jqDfPm6RhbDqJg7rM784ZMN1hZWb7BJEF5WdK'), is_signer=False, is_writable=True
                ),

                # 2
                AccountMeta(
                    associated_spl_token_address, is_signer=False, is_writable=True
                ),

                # 3
                AccountMeta(
                    Pubkey.from_string('8LU4ULP6DLTYKRthjT5FkJ7oCFM1tPLm9TEQ2BQAnfGb'), is_signer=False, is_writable=True
                ),

                # 4
                AccountMeta(
                    expected_pubkey, is_signer=False, is_writable=True
                ),

                # 5
                AccountMeta(
                    Pubkey.from_string('2gEGvFXGjuhBGQYGLnKVbrCpW4uKFtKhK7CevWdxMNjA'), is_signer=False, is_writable=True
                ),

                # 6
                AccountMeta(
                    Pubkey.from_string('5Gk1kTdDqqacmA2UF3UbNhM7eEhVFvF3p8nd9p3HbXxk'), is_signer=False, is_writable=False
                ),

                # 7
                AccountMeta(
                    associated_eth_token_address, is_signer=False, is_writable=True
                ),

                # 8
                AccountMeta(
                    Pubkey.from_string('AbefESHCRKZKQbdcAD8qes4EjzQfzMN1KkCCMsz7TogL'), is_signer=False, is_writable=True
                ),

                # 9
                AccountMeta(
                    Pubkey.from_string('29w3f87B9gAkLY3m9rTsob67gvMbg58XsBCTTugMBgfN'), is_signer=False, is_writable=True
                ),

                # 10
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),

                # 11
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),

                # 12
                AccountMeta(
                    Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'), is_signer=False, is_writable=False
                ),
                
                # 13
                AccountMeta(
                    Pubkey.from_string('8LU4ULP6DLTYKRthjT5FkJ7oCFM1tPLm9TEQ2BQAnfGb'), is_signer=False, is_writable=True
                ),
                    
            ],
            data=bytes.fromhex('0fffffffffffffffff')
        )
        all_instruction.append(withdraw_obligation_collateral_and_redeem_reserve_collateral_instruction)
        
        # 8. CloseAccount
        close_account_instruction = Instruction(
            program_id=Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
            accounts=[
                AccountMeta(
                    associated_eth_token_address, is_signer=False, is_writable=True
                ),
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),
                AccountMeta(
                    self.address, is_signer=True, is_writable=True
                ),
            ],
            data=bytes.fromhex('09')
        )
        all_instruction.append(close_account_instruction)

        message = MessageV0.try_compile(
            payer=self.address,
            instructions=[
                *all_instruction
            ],
            address_lookup_table_accounts=[],
            recent_blockhash=(await self.client.get_latest_blockhash("confirmed")).value.blockhash,
        )

        tx = VersionedTransaction(
            message=message,
            keypairs=[self.account]
        )

        # Отправка транзакции
        try:
            tx_hash_ = await self.client.send_raw_transaction(
                txn=bytes(tx),
                opts=TxOpts(
                    skip_confirmation=True,
                    skip_preflight=False,
                    preflight_commitment=Confirmed,
                )
            )
            tx_hash = tx_hash_.value
            #print(f"Transaction sent: {tx_hash}")

            # Проверка статуса транзакции
            tx_status = await self.get_tx_status(signature=tx_hash)

            if tx_status["success"]:
                return True, tx_hash
            else:
                return False, tx_hash
            
        except RPCException as e:

            if exception_counter > 1:
                return False, e

            return await self.start_withdraw_eth_safe_finance(exception_counter + 1)
                
        except Exception as e:
            return False, e

    async def get_tx_base_64(self, account_data: Accounts):
        try:
            program_id = Pubkey.from_string("turboe9kMc3mSR8BosPkVzoHUfn5RVNzZhkrT2hdGxN") 
            seed1 = b"clicker"
            seed2 = bytes(self.address)
            first_address, _ = Pubkey.find_program_address([seed1, seed2], program_id)

            
            seed1 = b"user"
            seed2 = bytes(self.address)
            second_address, _ = Pubkey.find_program_address([seed1, seed2], program_id)


            # 1. SetComputeUnitLimit
            compute_budget_program_id = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
            data = random.randint(40000, 50000)
            set_compute_unit_limit_instruction = Instruction(
                program_id=compute_budget_program_id,
                accounts=[],
                data=bytes([2]) + (data).to_bytes(4, "little")
            )

            # 2. Unknown Instruction
            header = bytes.fromhex('b413b1346fe0308b')
            value = account_data.turbo_tap_ref_code.encode("utf-8")
            value_data = header + value

            unknown_instruction = Instruction(
                program_id=Pubkey.from_string('turboe9kMc3mSR8BosPkVzoHUfn5RVNzZhkrT2hdGxN'),
                accounts=[
                    AccountMeta(second_address, is_signer=False, is_writable=True),
                    AccountMeta(first_address, is_signer=False, is_writable=True),
                    AccountMeta(self.address, is_signer=True, is_writable=True),
                    AccountMeta(Pubkey.from_string('11111111111111111111111111111111'), is_signer=False, is_writable=False),
                    AccountMeta(Pubkey.from_string('9FXCusMeR26k1LkDixLF2dw1AnBX8SsB2cspSSi3BcKE'), is_signer=False, is_writable=False),
                    AccountMeta(Pubkey.from_string('tBEwvhbQVKJpR66VGQV6ztqFQAureknjvn51eMKfieD'), is_signer=True, is_writable=False),
                ],
                data=value_data
            )
            
            import ast

            # Функция для преобразования JSON строки в список чисел
            def json_to_list(json_str):
                return ast.literal_eval(json_str)
            
            json_tx = {
                "signatures": [
                    [2],
                    [0] * 64,  # Заглушка для подписи
                    [0] * 64   # Вторая заглушка для подписи
                ],
                "message": {
                    "header": {
                        "numRequiredSignatures": 2,
                        "numReadonlySignedAccounts": 1,
                        "numReadonlyUnsignedAccounts": 4
                    },
                    "accountKeys": [
                        [8],
                        json_to_list(self.address.to_json()),
                        json_to_list(Pubkey.from_string('tBEwvhbQVKJpR66VGQV6ztqFQAureknjvn51eMKfieD').to_json()),
                        json_to_list(second_address.to_json()),
                        json_to_list(first_address.to_json()),
                        json_to_list(Pubkey.from_string('11111111111111111111111111111111').to_json()),
                        json_to_list(Pubkey.from_string('9FXCusMeR26k1LkDixLF2dw1AnBX8SsB2cspSSi3BcKE').to_json()),
                        json_to_list(Pubkey.from_string('ComputeBudget111111111111111111111111111111').to_json()),
                        json_to_list(Pubkey.from_string('turboe9kMc3mSR8BosPkVzoHUfn5RVNzZhkrT2hdGxN').to_json())
                    ],
                    "recentBlockhash": json_to_list(
                        Pubkey.from_string(
                            str((await self.client.get_latest_blockhash("confirmed")).value.blockhash)
                        ).to_json()
                    ),
                    "instructions": [
                        [2],
                        {
                            "programIdIndex": 6,
                            "accounts": [[0]],
                            "data": [[len(json.loads(set_compute_unit_limit_instruction.to_json())['data'])]] +
                                    json.loads(set_compute_unit_limit_instruction.to_json())['data']
                        },
                        {
                            "programIdIndex": 7,
                            "accounts": [[6], 2, 3, 0, 4, 5, 1],
                            "data": [[len(json.loads(unknown_instruction.to_json())['data'])]] +
                                    json.loads(unknown_instruction.to_json())['data']
                        }
                    ]
                }
            }

            message = Message.from_json(json.dumps(json_tx['message'], separators=(",", ":")))

            my_signature = self.account.sign_message(to_bytes_versioned(message))

            json_tx["signatures"][1] = json_to_list(my_signature.to_json())

            tx = Transaction.from_json(json.dumps(json_tx, separators=(",", ":")))
            
            return True, base64.b64encode(bytes(tx)).decode("utf-8")
        except Exception as e:
            False, e