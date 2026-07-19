# aionatureremo

Asynchronous Python client for the [Nature Remo Cloud API](https://developer.nature.global/).

Built for Home Assistant: aiohttp session injection, fully typed, no dependencies beyond aiohttp.

## Usage

```python
import aiohttp
from aionatureremo import NatureRemoClient

async with aiohttp.ClientSession() as session:
    client = NatureRemoClient("YOUR_ACCESS_TOKEN", session)
    devices = await client.get_devices()
```

Get an access token at https://home.nature.global/.
