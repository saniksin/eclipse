import random
import traceback

from fake_useragent import UserAgent
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from db_api.database import get_account, db
from db_api.models import Accounts
from clients.eth.eth_client import EthClient
from clients.sol.sol_client import SolanaClient
from data.config import logger
from settings.settings import RPC_DICT


class ImportToDB:
    imported = []
    edited = []

    @staticmethod
    async def add_info_to_db(accounts_data: list[dict]) -> None:
        """
        Добавляет или обновляет информацию об аккаунтах в базе данных.
        :param accounts_data: список словарей с полями 'solana_pk', 'evm_pk', 'proxy'
        """
        async with AsyncSession(db.engine) as session:
            if not accounts_data:
                logger.info('There are no wallets in the file!')
                return

            total = len(accounts_data)
            logger.info(f'Начинаем импорт {total} аккаунтов')

            for num, account in enumerate(accounts_data, start=1):
                logger.info(f'Импортирую аккаунт {num} из {total}')
                try:
                    sol_pk = account['solana_pk']
                    evm_pk = account['evm_pk']
                    proxy = account['proxy']
                    # twitter = account['twitter']
                    # discord = account['discord']
                    # invite_code = account['invite_code']

                    # Генерируем User-Agent (по желанию можно вынести логику рандома отдельно)
                    user_agent = UserAgent().chrome
                    if 'iPhone' in user_agent or 'iPad' in user_agent:
                        while True:
                            user_agent = UserAgent().chrome
                            if 'iPhone' not in user_agent and 'iPad' not in user_agent:
                                break
                            
                    # Получаем Solana-адрес
                    sol_client = SolanaClient(sol_pk=sol_pk, proxy=proxy, rpc=RPC_DICT['ECLIPSE'])
                    sol_address = str(sol_client.address)

                    # Если есть EVM-приватник, получаем EVM-адрес
                    if evm_pk:
                        evm_client = EthClient(
                            private_key=evm_pk,
                            proxy=proxy,
                            user_agent=user_agent
                        )
                        evm_address = evm_client.account.address
                    else:
                        evm_address = ''

                    # Проверяем, есть ли уже запись в БД
                    account_instance = await get_account(sol_pk=sol_pk)

                    if account_instance:
                        # Обновляем, если есть изменения
                        await ImportToDB.update_account_instance(
                            session,
                            account_instance,
                            sol_address,
                            evm_pk,
                            evm_address,
                            proxy,
                            # twitter,
                            # discord,
                            # invite_code
                        )
                    else:
                        # Создаём новую запись
                        account_instance = Accounts(
                            sol_pk=sol_pk,
                            sol_address=sol_address,
                            evm_pk=evm_pk,
                            evm_address=evm_address,
                            proxy=proxy,
                            user_agent=user_agent,
                            # twitter=twitter,
                            # discord=discord,
                            # invite_code=invite_code
                        )
                        ImportToDB.imported.append(account_instance)
                        session.add(account_instance)

                except Exception as err:
                    logger.error(f'Ошибка при обработке аккаунта №{num}: {err}')
                    logger.exception('Stack Trace:')

            # Формируем текстовый отчёт
            report_lines = []

            if ImportToDB.imported:
                report_lines.append("\n--- Imported")
                report_lines.append("{:<4}{:<45}{:<45}{:<25}".format("N", "Sol Address", "EVM Address", "Proxy"))
                for i, wallet in enumerate(ImportToDB.imported, 1):
                    report_lines.append(
                        "{:<4}{:<45}{:<45}{:<25}".format(
                            i,
                            wallet.sol_address or "-",
                            wallet.evm_address or "-",
                            wallet.proxy or "-"
                        )
                    )

            if ImportToDB.edited:
                report_lines.append("\n--- Edited")
                report_lines.append("{:<4}{:<45}{:<45}{:<25}".format("N", "Sol Address", "EVM Address", "Proxy"))
                for i, wallet in enumerate(ImportToDB.edited, 1):
                    report_lines.append(
                        "{:<4}{:<45}{:<45}{:<25}".format(
                            i,
                            wallet.sol_address or "-",
                            wallet.evm_address or "-",
                            wallet.proxy or "-"
                        )
                    )

            # Логируем и выводим финальную информацию
            if report_lines:
                full_report = "\n".join(report_lines)
                logger.info(full_report)  # Выводим в лог
                #print(full_report)        # Дублируем в консоль

            logger.info(
                f"Импорт завершён! "
                f"Импортировано: {len(ImportToDB.imported)} из {total}. "
                f"Обновлено: {len(ImportToDB.edited)} из {total}."
            )
            print(
                f"Done! {len(ImportToDB.imported)}/{total} wallets were imported, "
                f"and {len(ImportToDB.edited)}/{total} wallets were updated."
            )

            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback() 
                if "UNIQUE constraint failed" in str(e.orig):
                    print(f"Ошибка: Дублирующая запись. Данные не добавлены: {e}")
                    return
                else:
                    print(f"Неожиданная ошибка: {e}")
                    return


    @staticmethod
    async def update_account_instance(
        session: AsyncSession,
        account_instance: Accounts,
        sol_address: str,
        evm_pk: str,
        evm_address: str,
        proxy: str,
        # twitter: str,
        # discord: str,
        # invite_code: str
    ) -> None:
        """
        Обновляет поля account_instance, если они отличаются от текущих.

        :param session: активная сессия SQLAlchemy
        :param account_instance: модель аккаунта, которую нужно обновить
        :param sol_address: обновлённый Solana-адрес
        :param evm_pk: обновлённый приватный ключ (EVM)
        :param evm_address: обновлённый адрес (EVM)
        :param proxy: обновлённый прокси
        """
        has_changed = False

        if account_instance.sol_address != sol_address:
            account_instance.sol_address = sol_address
            has_changed = True

        if account_instance.evm_pk != evm_pk:
            account_instance.evm_pk = evm_pk
            has_changed = True

        if account_instance.evm_address != evm_address:
            account_instance.evm_address = evm_address
            has_changed = True

        if account_instance.proxy != proxy:
            account_instance.proxy = proxy
            has_changed = True

        # if account_instance.twitter_token != twitter:
        #     account_instance.twitter_token = twitter
        #     account_instance.twitter_account_status = "UKNOWN"
        #     has_changed = True

        # if account_instance.discord_token != discord:
        #     account_instance.discord_token = discord
        #     has_changed = True

        # if account_instance.turbo_tap_invite_code != invite_code:
        #     account_instance.turbo_tap_invite_code = invite_code
        #     has_changed = True
  
        if has_changed:
            ImportToDB.edited.append(account_instance)
            await session.merge(account_instance)
