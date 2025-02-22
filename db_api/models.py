import datetime

from data.auto_repr import AutoRepr
from sqlalchemy import Column, Integer, Text, Boolean, DateTime
from sqlalchemy.orm import declarative_base


Base = declarative_base()


class Accounts(Base, AutoRepr):
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)

    sol_pk = Column(Text, unique=True)
    sol_address = Column(Text, unique=True) 
    evm_pk = Column(Text)
    evm_address = Column(Text)
    proxy = Column(Text)
    user_agent = Column(Text)

    # задачи
    bridge_complete = Column(Boolean)
    swap = Column(DateTime)

    # Turbo Tap social
    twitter_token = Column(Text)
    discord_token = Column(Text)

    # turbo tap
    turbo_tap_ref_code = Column(Text)
    turbo_tap_is_registered = Column(Boolean)
    turbo_tap_pubkey = Column(Text)
    turbo_tap_pk = Column(Text)
    turbo_tap_tap_finished = Column(Text)
    turbo_tap_points = Column(Integer)
    turbo_tap_passive_earning = Column(Integer)
    turbo_tap_rank = Column(Integer)

    # astrol usdc deposit
    astrol_usdc_account_registed = Column(Boolean)
    astrol_usdc_deposited = Column(Boolean)
    astrol_sum_deposited = Column(Integer)
    astrol_account_pk = Column(Text)

    # safe_finance
    save_finance_account_registed = Column(Boolean)
    save_finance_eth_deposited = Column(Boolean)
    save_finance_sum_deposited = Column(Integer)

    finished = Column(Boolean)

    def __init__(
            self,
            sol_pk: str,
            sol_address: str,
            evm_pk: str,
            evm_address: str,
            proxy: str,
            user_agent: str
    ) -> None:
        
        self.sol_pk = sol_pk
        self.sol_address = sol_address
        self.evm_pk = evm_pk
        self.evm_address = evm_address
        self.proxy = proxy
        self.user_agent = user_agent

        self.bridge_complete = False
        self.swap = datetime.datetime(1970, 1, 1)
        
        # Turbo Tap social
        self.twitter_token = ''
        self.discord_token = ''

        # turbo tap
        self.turbo_tap_ref_code = ''
        self.turbo_tap_is_registered = False
        self.turbo_tap_pubkey = ''
        self.turbo_tap_pk = ''
        self.turbo_tap_tap_finished = False
        self.turbo_tap_points = 0
        self.turbo_tap_passive_earning = 0
        self.turbo_tap_rank = 0

        self.astrol_usdc_account_registed = False
        self.astrol_usdc_deposited = False
        self.astrol_sum_deposited = 0
        self.astrol_account_pk = ''

        self.save_finance_account_registed = False
        self.save_finance_eth_deposited = False
        self.save_finance_sum_deposited = 0

        self.finished = False