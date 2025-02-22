####################### RPC #####################
RPC_DICT = {
    #"ECLIPSE": "https://https://eclipse.helius-rpc.com",
    "ECLIPSE": "https://mainnetbeta-rpc.eclipse.xyz"
}

####################### ASYNC_TASK_IN_SAME_TIME #####################
ASYNC_TASK_IN_SAME_TIME = 1
SLEEP_BEETWEEN_ACTIONS = [1, 10]
NUMBER_OF_ATTEMPTS = 10
MIN_ECLIPSE_ETH_AMOUNT = 0.00053
SHUFFLE_ACCOUNTS = True
SLEEP_BEETWEEN_START_TAP_ACTIONS = [10, 30]
TURBO_TAP_AMOUNT_TO_DEPOSIT = 500000 # 0.0005 ETH !!! Прописываем в Wei, decimals 9 в Eclipse!
MAX_TURBO_TAP_POINTS = 20_000
####################### BRIDGE SETTINGS #####################

# RELAY
RELAY_MAX_SLIPPAGE = 1

# не трогать!
RELAY_FINAL_SLIPPAGE = RELAY_MAX_SLIPPAGE * 100

RELAY_BRIDGE_NETWORK_APPLY = {
    "Arbitrum": True,
    "Optimism": True,
    "Base": True,
    "Ethereum": False,
}

AMOUNT_TO_BRIDGE = [0.0015, 0.0021]   # FROM / TO (SEC!)
DEPOSIT_ALL_BALANCE = True
MIN_AMOUNT_IN_NETWORK = [0.000015, 0.000030]
MIN_AMOUNT_TO_BRIDGE = 0.0015

####################### SWAP SETTINGS ######################
TO_WAIT_TX = 1     # Ожидаем транзу в минутах
MIX_SWAP = ["ORCA", "SOLAR"] # Через что будем делать свапы в MIX свап

SWAP_SETTINGS = {
    "ORCA": {
        "SWAP_ETH_TO": ['USDC', 'tETH', 'SOL'], # МОЖНО ДОБАВИТЬ # SOL, # USDT
        "TOKEN_TO_ETH": ['USDC', 'tETH', 'SOL'], # МОЖНО ДОБАВИТЬ # SOL, # USDT
        "NATIVE_ETH_TO_SWAP": [0.0044, 0.0058],
        "USE_STATIC_AMOUNT": False,
        "PERCENT_ETH_TO_SWAP": [70, 80],
        "MIN_TOKEN_SWAP_USD_VALUE": 0.1,
    },
    "SOLAR": {
        "SWAP_ETH_TO": ['USDC', 'tETH'],
        "TOKEN_TO_ETH": ['USDC', 'tETH'],
        "NATIVE_ETH_TO_SWAP": [0.0044, 0.0058],
        "USE_STATIC_AMOUNT": False,
        "PERCENT_ETH_TO_SWAP": [70, 80],
        "MIN_TOKEN_SWAP_USD_VALUE": 0.1,
    }
}

USE_SWAP_LIMIT_PER_DATA = True       # Если сделается свап, прогресс будет записан и следующий свап будет возможен только через SWAP_DATA_LIMIT
SWAP_DATA_LIMIT = [1, 4]             # DAY

# TurboTap
CLAIM_DOMAIN_VIA = 'AllDomains'  #TurboTap, AllDomains

# Astrol
MIN_USDC_BALANCE = 2
PERSENT_TO_LENDING_FROM_ETH = [60, 80] # для astrol и для Save ОДИНАКОВО!!!!!!

# Captcha
CAPTCHA_SERVICE = 'BESTCAPTCHA' # CAPTCHA24

API_KEY_24_CAPTCHA = ""
API_KEY_BESTCAPTCHA = ""
API_KEY_RAZORCAP = ""
SITEKEY = "a9b5fb07-92ff-493f-86fe-352a2803b3df"