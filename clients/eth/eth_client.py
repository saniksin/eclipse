import random
from typing import Optional

from web3 import AsyncWeb3
from web3.eth import AsyncEth
from eth_account.signers.local import LocalAccount
from fake_useragent import UserAgent

from data.models import Network, Networks
from data.config import logger
from data.models import Wallet, Contracts, Transactions


class EthClient:
    network: Network
    account: Optional[LocalAccount]
    w3: AsyncWeb3

    def __init__(
            self, 
            private_key: Optional[str] = None, 
            network: Network = Networks.Ethereum,
            proxy: Optional[str] = None, 
            user_agent: Optional[str] = None,
        ) -> None:

        self.network = network
        self.headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'user-agent': user_agent
        }
        
        self.proxy = proxy

        self.w3 = AsyncWeb3(
            provider=AsyncWeb3.AsyncHTTPProvider(
                endpoint_uri=self.network.rpc,
                request_kwargs={'proxy': self.proxy, 'headers': self.headers}
            ),
            modules={'eth': (AsyncEth,)},
            middleware=[]
        )
        
        if private_key:
            self.account = self.w3.eth.account.from_key(private_key=private_key)

        else:
            logger.warning('RANDOM PRIVATE KEY GENERATED!')
            self.account = self.w3.eth.account.create(extra_entropy=str(random.randint(1, 999_999_999)))
        
        self.wallet = Wallet(self)
        self.contracts = Contracts(self)
        self.transactions = Transactions(self)
    