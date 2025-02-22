from datetime import datetime, timezone

from sqlalchemy.sql import func
from sqlalchemy.future import select

from db_api import sqlalchemy_
from db_api.models import Accounts, Base
from data.config import ACCOUNTS_DB
from typing import List, Optional
from settings.settings import MAX_TURBO_TAP_POINTS


db = sqlalchemy_.DB(f'sqlite+aiosqlite:///{ACCOUNTS_DB}', pool_recycle=3600, connect_args={'check_same_thread': False})


async def get_account(sol_pk: str) -> Optional[Accounts]:
    return await db.one(Accounts, Accounts.sol_pk == sol_pk)

async def get_accounts(
        quest: str
) -> List[Accounts]:
    
    today = datetime.now(timezone.utc).date()

    if quest in {'BRIDGE_RELAY', 'BRIDGE_OFFICIAL'}:
        query = select(Accounts).where(
            Accounts.bridge_complete == False,
            Accounts.evm_pk.isnot(None),
            Accounts.finished != True
        )
    elif quest in {
            'ORCA_NATIVE_TO_TOKEN', 
            'ORCA_TOKEN_TO_NATIVE',
            'SOLAR_NATIVE_TO_NATIVE', 
            'SOLAR_TOKEN_TO_NATIVE',
            'MIX_NATIVE_TO_TOKEN',
            'MIX_TOKEN_TO_NATIVE',
        }: 
        query = select(Accounts).where(
            func.date(Accounts.swap) <= today,
            Accounts.finished != True
        )
    elif quest in {'TurboTap'}: 
        query = select(Accounts).where(
            Accounts.turbo_tap_is_registered == True,
            Accounts.turbo_tap_tap_finished == False,
            Accounts.turbo_tap_points < MAX_TURBO_TAP_POINTS,
            Accounts.finished != True
        )
    elif quest in {'ASTROL_DEPOSIT'}:
        query = select(Accounts).where(
            Accounts.astrol_usdc_deposited == False,
            Accounts.finished != True
        )
    elif quest in {'ASTROL_WITHDRAW'}:
        query = select(Accounts).where(
            Accounts.astrol_usdc_deposited == True,
            Accounts.finished != True
        )
    elif quest in {'SAVE_DEPOSIT'}:
        query = select(Accounts).where(
            Accounts.save_finance_eth_deposited == False,
            Accounts.finished != True
        )
    elif quest in {'SAVE_WITHDRAW'}:
        query = select(Accounts).where(
            Accounts.save_finance_eth_deposited == True,
            Accounts.finished != True
        )
    elif quest in {'TurboTap (Registration)'}:
        query = select(Accounts).where(
            Accounts.twitter_token != '',
            Accounts.discord_token != '',
            Accounts.turbo_tap_ref_code != '',
            Accounts.turbo_tap_is_registered == False,
            Accounts.finished != True
        )
    elif quest in {'TurboTap (ParseStats)'}:
        query = select(Accounts).where(
            Accounts.turbo_tap_is_registered == True,
            Accounts.turbo_tap_points == 0,
            Accounts.finished != True
        )
    elif quest in {'TurboTap (ParseRefCodes)'}:
        query = select(Accounts).where(
            Accounts.turbo_tap_is_registered == True,
            Accounts.finished != True
        )
    else:
        query = select(Accounts)   
    return await db.all(query)

async def initialize_db():
    await db.create_tables(Base)
