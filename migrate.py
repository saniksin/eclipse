import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError

from db_api.database import db, Accounts, get_accounts
from data.config import logger


async def migrate():
    async with AsyncSession(db.engine) as session:

        # Добавляем колонку twitter_account_status с дефолтным значением 'UNKNOWN'
        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_is_registered BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_pubkey TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_pk TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_tap_finished BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN astrol_usdc_account_registed BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN astrol_usdc_deposited BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN astrol_sum_deposited INTEGER DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN astrol_account_pk TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_points INTEGER DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN save_finance_account_registed BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN save_finance_eth_deposited BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN save_finance_sum_deposited INTEGER DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN twitter_token TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass
        
        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN discord_token TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass

        #####

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_ref_code TEXT DEFAULT '';
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_passive_earning INTEGER DEFAULT 0;
                """)
            )
        except OperationalError:
            pass
        
        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN turbo_tap_rank INTEGER DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        try:
            await session.execute(
                text("""
                    ALTER TABLE accounts
                    ADD COLUMN finished BOOLEAN DEFAULT 0;
                """)
            )
        except OperationalError:
            pass

        await session.commit()
        await session.close()

    logger.success('Migration completed.')