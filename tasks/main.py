import asyncio
import random
import traceback
import random

from data.router import possible_router
from data.config import logger, tasks_lock, completed_tasks, remaining_tasks, DISCORD_TOKEN_SUCCESS, DISCORD_TOKEN_FAILS, DISCORD_PROXYS, DISCORD_TOKENS
from db_api.models import Accounts
from db_api.database import get_accounts
from tasks import RelayBridge, OrcaSwap, TurboTap, AstrolLending, SolarSwap, SaveFinance, DiscordInvite
from settings.settings import SLEEP_BEETWEEN_ACTIONS, MIX_SWAP, SHUFFLE_ACCOUNTS
from tqdm import tqdm


async def get_start(semaphore, quest: str | list):
    #try:
        if isinstance(quest, str):
            accounts: list[Accounts] = await get_accounts(quest)
            #accounts = accounts[[accounts[0]]]
        else:
            accounts: list[dict] = quest
        # accounts = []
        # for address in all_accounts:
        #     if address.sol_address == "":
        #         accounts.append(address)
        #         break
        #accounts = [accounts[2]]
        
        # print(len(accounts))
        # print(accounts[0].sol_address)
        # #return
        if len(accounts) != 0:
            if SHUFFLE_ACCOUNTS:
                random.shuffle(accounts)
            #random.shuffle(accounts)
            logger.info(f'Всего задач: {len(accounts)}')
            tasks = []
            if isinstance(quest, str):
                for account_data in accounts:
                    task = asyncio.create_task(start_limited_task(semaphore, accounts, account_data, quest=quest))
                    tasks.append(task)
            else:
                account_number = 1
                for account_data in accounts:
                    task = asyncio.create_task(start_limited_task(semaphore, accounts, account_data, quest=account_number))
                    tasks.append(task)
                    account_number += 1

            await asyncio.wait(tasks)
        else:
            msg = (f'Не удалось начать действие, причина: нет подходящих аккаунтов для выбранного действия.')
            logger.warning(msg)
    # except Exception as e:
    #     pass


async def start_limited_task(semaphore, accounts, account_data, quest):
    #try:
        async with semaphore:
            status = await start_task(account_data, quest)
            async with tasks_lock:
                completed_tasks[0] += 1
                remaining_tasks[0] = len(accounts) - completed_tasks[0]

            logger.warning(f'Всего задач: {len(accounts)}. Осталось задач: {remaining_tasks[0]}')

            if isinstance(quest, str):
                if remaining_tasks[0] > 0 and status and quest not in {'TurboTap (ParseRefCodes)', 'TurboTap (ParseStats)'}:
                    # Генерация случайного времени ожидания
                    sleep_time = random.randint(SLEEP_BEETWEEN_ACTIONS[0], SLEEP_BEETWEEN_ACTIONS[1])

                    logger.info(f"Ожидание {sleep_time} между действиями...")
                    
                    for _ in tqdm(range(sleep_time), desc=f"{account_data.sol_address} | Ждем после действия", unit="сек"):
                        await asyncio.sleep(1)
            else:
                async with tasks_lock:
                    if status:
                        with open(DISCORD_TOKEN_SUCCESS, 'a') as file:
                            file.write(f"{account_data['discord_token']}\n")
                    else:
                        with open(DISCORD_TOKEN_FAILS, 'a') as file:
                            file.write(f"{account_data['discord_token']}\n")
                    
                    # Читаем все токены из файла
                    with open(DISCORD_TOKENS, 'r') as file:
                        discord_tokens: list[str] = [row.strip() for row in file]

                    # Удаляем токен, если он есть
                    discord_tokens = [token for token in discord_tokens if token != account_data['discord_token']]

                    # Перезаписываем файл без указанного токена
                    with open(DISCORD_TOKENS, 'w') as file:
                        file.write('\n'.join(discord_tokens) + '\n')

                    # Читаем все прокси из файла
                    with open(DISCORD_PROXYS, 'r') as file:
                        discord_proxys: list[str] = [row.strip() for row in file]

                    # Удаляем прокси, если он есть
                    discord_proxys = [proxy for proxy in discord_proxys if proxy != account_data['discord_proxy']]

                    # Перезаписываем файл без указанного прокси
                    with open(DISCORD_PROXYS, 'w') as file:
                        file.write('\n'.join(discord_proxys) + '\n')
                
                # if remaining_tasks[0] > 0:

                #     sleep_time = random.randint(SLEEP_BEETWEEN_ACTIONS[0], SLEEP_BEETWEEN_ACTIONS[1])
                #     logger.info(f"Ожидание {sleep_time} между действиями...")
                #     for _ in tqdm(range(sleep_time), desc=f"{account_data['discord_token']} | Ждем после действия", unit="сек"):
                #         await asyncio.sleep(1)
                    
    # except asyncio.CancelledError:
    #     pass



async def start_task(account_data, quest):

    #try:
    if isinstance(quest, str):
        if quest == "BRIDGE_RELAY":
            async with RelayBridge(data=account_data) as relay:
                status = await relay.start_task()
        elif quest == "ORCA_NATIVE_TO_TOKEN":
            async with OrcaSwap(data=account_data) as orca:
                status = await orca.swap_native_to_token()
        elif quest == "ORCA_TOKEN_TO_NATIVE":
            async with OrcaSwap(data=account_data) as orca:
                status = await orca.swap_token_to_native()
        elif quest == "TurboTap":
            async with TurboTap(data=account_data) as turbo:
                status = await turbo.start_turbo_tap()
        elif quest == "TurboTap (Registration)":
            async with TurboTap(data=account_data) as turbo:
                status = await turbo.start_registration()
        elif quest == 'ASTROL_DEPOSIT':
            async with AstrolLending(data=account_data) as astrol:
                status = await astrol.start_deposit()
        elif quest == 'ASTROL_WITHDRAW':
            async with AstrolLending(data=account_data) as astrol:
                status = await astrol.start_withdraw()
        elif quest == 'SOLAR_NATIVE_TO_TOKEN':
            async with SolarSwap(data=account_data) as solar:
                status = await solar.swap_native_to_token()
        elif quest == 'SOLAR_TOKEN_TO_NATIVE':
            async with SolarSwap(data=account_data) as solar:
                status = await solar.swap_token_to_native()

        elif quest == "MIX_NATIVE_TO_TOKEN":

            platform = random.choice(MIX_SWAP) 
            logger.warning(f'[{account_data.id}] | {account_data.sol_address} свап NATIVE to TOKEN via {platform}')

            async with possible_router.get(platform)(data=account_data) as swap_platform:
                status = await swap_platform.swap_native_to_token()
            
        elif quest == "MIX_TOKEN_TO_NATIVE":

            platform = random.choice(MIX_SWAP) 
            logger.warning(f'[{account_data.id}] | {account_data.sol_address} свап TOKEN to NATIVE via {platform}')

            async with possible_router.get(platform)(data=account_data) as swap_platform:
                status = await swap_platform.swap_token_to_native()

        elif quest == 'SAVE_DEPOSIT':
            async with SaveFinance(data=account_data) as save:
                status = await save.start_deposit()
        elif quest == 'SAVE_WITHDRAW':
            async with SaveFinance(data=account_data) as save:
                status = await save.start_withdraw()
        elif quest == 'TurboTap (ParseRefCodes)':
            async with TurboTap(data=account_data) as turbo:
                status = await turbo.parse_ref_codes()
        elif quest == 'TurboTap (ParseStats)':
            async with TurboTap(data=account_data) as turbo:
                status = await turbo.parse_stats()
    else:
        discord = DiscordInvite(account_data, quest)
        status = await discord.start_accept_discord_invite()
    
    return status
    # except TypeError:
    #     pass

    # except Exception as error:
    #     logger.error(f'{account_data.sol_address} | Неизвестная ошибка: {error}')
    #     print(traceback.print_exc())