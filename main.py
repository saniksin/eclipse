import sys
import itertools

import asyncio

from data.config import logger
from utils.create_files import create_files
from db_api.database import initialize_db
from utils.adjust_policy import set_windows_event_loop_policy
from data.config import EVM_PKS, SOL_PKS, PROXIES, DISCORD_PROXYS, DISCORD_TOKENS, logger
from utils.import_info import get_info
from utils.user_menu import get_action, swap_menu, swap_menu_token, bridge_menu, lending_menu, astrol_menu, tap_menu, save_menu
from db_api.start_import import ImportToDB
from settings.settings import ASYNC_TASK_IN_SAME_TIME
from tasks.main import get_start
from migrate import migrate
from utils.reset_count_progress import set_progress_to_zero
from utils.headers import compute_version, assemble_build


def main():
    global remaining_tasks

    solana_pks = get_info(SOL_PKS)
    evm_pks = get_info(EVM_PKS)
    proxies = get_info(PROXIES)
    # twitter_tokens = get_info(TWITTER_TOKENS)
    # discord_tokens = get_info(DISCORD_TOKENS)
    # invite_codes = get_info(INVITE_CODES)

    logger.info(f'\n\n\n'
                f'Загружено в solana_pks.txt {len(solana_pks)} аккаунтов SOL \n'
                f'Загружено в evm_pks.txt {len(evm_pks)} аккаунтов EVM \n'
                f'Загружено в proxies.txt {len(proxies)} прокси \n'
                # f'Загружено в twitter_tokens.txt {len(twitter_tokens)} твиттер токенов \n'
                # f'Загружено в discord_tokens.txt {len(discord_tokens)} дискорд токенов \n'
                # f'Загружено в turbo_tap_invite_codes.txt {len(invite_codes)} turbo-tap invite кодов \n'
    )

    cycled_proxies_list = itertools.cycle(proxies) if proxies else None

    formatted_data: list = [{
            'solana_pk': sol_pk,
            'evm_pk': evm_pks.pop(0) if evm_pks else None,
            'proxy': next(cycled_proxies_list) if cycled_proxies_list else None,
            # 'twitter': twitter_tokens.pop(0) if twitter_tokens else None,
            # 'discord': discord_tokens.pop(0) if discord_tokens else None,
            # 'invite_code': invite_codes.pop(0) if invite_codes else None,
        } for sol_pk in solana_pks
    ]

    while True:
        set_progress_to_zero()

        user_choice = get_action()

        semaphore = asyncio.Semaphore(ASYNC_TASK_IN_SAME_TIME)

        match user_choice:

            case "Import data to db":
                asyncio.run(ImportToDB.add_info_to_db(accounts_data=formatted_data))

            case "Bridge":
                bridge_choise = bridge_menu()
                if bridge_choise.upper() == 'RELAY':
                    asyncio.run(get_start(semaphore, "BRIDGE_RELAY"))
                    
            case "Swap":
                swap_choice = swap_menu()
                if swap_choice == "ORCA":
                    orca_choice = swap_menu_token()
                    match orca_choice:
                        case "Swap native to token":
                            asyncio.run(get_start(semaphore, "ORCA_NATIVE_TO_TOKEN"))
                        case "Swap token to native":
                            asyncio.run(get_start(semaphore, "ORCA_TOKEN_TO_NATIVE"))
                elif swap_choice == "SOLAR":
                    solar_choice = swap_menu_token()
                    match solar_choice:
                        case "Swap native to token":
                            asyncio.run(get_start(semaphore, "SOLAR_NATIVE_TO_TOKEN"))
                        case "Swap token to native":
                            asyncio.run(get_start(semaphore, "SOLAR_TOKEN_TO_NATIVE"))
                elif swap_choice == 'MIX (SOLAR, ORCA...)':
                    mix_choice = swap_menu_token()
                    match mix_choice:
                        case "Swap native to token":
                            asyncio.run(get_start(semaphore, "MIX_NATIVE_TO_TOKEN"))
                        case "Swap token to native":
                            asyncio.run(get_start(semaphore, "MIX_TOKEN_TO_NATIVE"))


            case "TurboTap":
                tap_choice = tap_menu()
                if tap_choice == "TurboTap (Tap)":
                    asyncio.run(get_start(semaphore, "TurboTap"))
                elif tap_choice == "TurboTap (Registrations)":
                    asyncio.run(get_start(semaphore, "TurboTap (Registration)"))
                elif tap_choice == "TurboTap (ParseStats)":
                    asyncio.run(get_start(semaphore, "TurboTap (ParseStats)"))
                elif tap_choice == "TurboTap (ParseRefCodes)":
                    asyncio.run(get_start(semaphore, "TurboTap (ParseRefCodes)"))
                    

            case "Lending":
                lending_choise = lending_menu()
                if lending_choise == "Astrol":
                    astrol_choice = astrol_menu()
                    match astrol_choice:
                        case "Deposit USDC":
                            asyncio.run(get_start(semaphore, "ASTROL_DEPOSIT"))
                        case "Withdraw USDC":
                            asyncio.run(get_start(semaphore, "ASTROL_WITHDRAW"))
                elif lending_choise == "SaveFinance":
                    save_choice = save_menu()
                    match save_choice:
                        case "Deposit ETH":
                            asyncio.run(get_start(semaphore, "SAVE_DEPOSIT"))
                        case "Withdraw ETH":
                            asyncio.run(get_start(semaphore, "SAVE_WITHDRAW"))

            case "Accept Eclipse Invite (Discord)":
                native_build = compute_version()
                logger.info(f'Успешно спрасил native_build приложения: {native_build}')
                client_build = assemble_build()
                logger.info(f'Успешно спрасил client_build приложения: {client_build}')
                discord_tokens = get_info(DISCORD_TOKENS)
                discord_proxys = get_info(DISCORD_PROXYS)

                logger.info(f'\n\n\n'
                    f'Загружено в discord_tokens.txt {len(discord_tokens)} дискорд токенов \n'
                    f'Загружено в discord_proxys.txt {len(discord_proxys)} прокси \n'
                )

                formatted_discord_data: list = [{
                        'discord_token': discord_token,
                        'discord_proxy': discord_proxys.pop(0) if discord_proxys else None,
                        'native_build': native_build,
                        'client_build': client_build
                    } for discord_token in discord_tokens
                ]
            
                if formatted_discord_data:
                    asyncio.run(get_start(semaphore, formatted_discord_data))
                else:
                    logger.error(f'Вы не добавили дискорд прокси или дискорд токенов!!!')
                    sys.exit(1)

            case "Exit":
                sys.exit(1)


if __name__ == "__main__":
    #try:
        asyncio.run(migrate())
        create_files()
        asyncio.run(initialize_db())
        set_windows_event_loop_policy()
        main()
    # except (SystemExit, KeyboardInterrupt):
    #     logger.info("Program closed")