import os
import sys

sys.path.append(os.path.dirname(os.path.realpath(__file__)))

import asyncio  # noqa: E402

from bydboxclient import BydBoxClient  # noqa: E402


async def main():
    boxclient = BydBoxClient('192.168.30.254', 8080, 1, 30)

    #task = asyncio.create_task(boxclient.init_data())
    await boxclient.init_data()

    for k, v in boxclient.data.items():
        print(f'{k} {v}')  # noqa: T201

if __name__ == "__main__":
    asyncio.run(main())
