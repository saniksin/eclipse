import asyncio
from data.session import BaseAsyncSession

async def create_razorcap_task(async_session: BaseAsyncSession, api_key, sitekey, proxy, rqdata):
    url = "https://api.razorcap.xyz/create_task"
    payload = {
        "key": api_key,
        "type": "hcaptcha_enterprise",
        "data": {
            "sitekey": sitekey,
            "siteurl": "discord.com",
            "proxy": 'http' + proxy,
            "rqdata": rqdata,
            "useragent": async_session.user_agent
        }
    }
    response = await async_session.post(url, json=payload)
    if response.status_code == 200:
        data = response.json()
        
        if data.get("status") == "success":
            return True, data.get("task_id")
        else:
            return False, data.get("error")
    else:
        return False, f"Failed to create task: HTTP {response.status_code}"

async def get_razorcap_task_result(async_session: BaseAsyncSession, task_id):
    url = f"https://api.razorcap.xyz/get_result/{task_id}"
    while True:
        response = await async_session.get(url)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "solved":
                return True, data.get("response_key")
            elif data.get("status") == "error":
                return False, data.get("error")
            else:
                await asyncio.sleep(2)  # Wait before polling again
        else:
            return False, f"Failed to get task result: HTTP {response.status_code}"
