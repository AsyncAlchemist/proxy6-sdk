# proxy6

A typed Python SDK for the [Proxy6.net](https://proxy6.net/en/developers) HTTP API.

Covers all nine documented endpoints — `getprice`, `getcount`, `getcountry`,
`getproxy`, `setdescr`, `buy`, `prolong`, `delete`, `check` — plus the
keyless `account` call. Responses are parsed into dataclasses with proper
types (`datetime`, `int`, `bool`, enums) instead of the raw strings the API
returns.

## Install

```sh
uv add proxy6
# or
pip install proxy6
```

Requires Python 3.13+.

## Quick start

```python
from proxy6 import Proxy6Client, Version

with Proxy6Client(api_key="YOUR_KEY") as client:
    info = client.account()
    print(f"Balance: {info.balance} {info.currency}")

    # How much for 10 Russian IPv6 proxies for 30 days?
    quote = client.get_price(count=10, period=30, version=Version.IPV6)
    print(quote.price, quote.price_single)

    # Buy them
    order = client.buy(
        count=10,
        period=30,
        country="ru",
        version=Version.IPV6,
        descr="scraper-pool",
    )
    for proxy in order.proxies:
        print(proxy.auth_url())  # http://user:pass@host:port
```

## API surface

| Method                                              | Purpose                                        |
| --------------------------------------------------- | ---------------------------------------------- |
| `account()`                                         | Balance / currency (calls API with no method)  |
| `get_price(count?, period?, version?)`              | Single-quote or full price table               |
| `get_count(country, version?)`                      | Available stock for a country                  |
| `get_country(version)`                              | List of ISO2 codes for a version               |
| `get_proxy(state?, descr?, page?, limit?)`          | List your proxies                              |
| `set_descr(new, old?, ids?)`                        | Rename the technical comment                   |
| `buy(count, period, country, version, descr?, ...)` | Purchase proxies                               |
| `prolong(period, ids)`                              | Extend existing proxies                        |
| `delete(ids?, descr?)`                              | Delete by id or by comment                     |
| `check(ids?, proxy?)`                               | Liveness check via id or `ip:port:user:pass`   |

### Enums

```python
from proxy6 import Version, State, ProxyType

Version.IPV4_SHARED  # 3
Version.IPV4         # 4
Version.MTPROTO      # 5
Version.IPV6         # 6

State.ACTIVE | State.EXPIRED | State.EXPIRING | State.ALL
ProxyType.HTTP | ProxyType.SOCKS
```

### Errors

The API uses an envelope of `{"status":"no","error_id":N,"error":"..."}`. The
SDK raises `Proxy6APIError` with `error_id` and `error` populated. The
documented codes are exported as `proxy6.ERROR_CODES`.

```python
from proxy6 import Proxy6APIError

try:
    client.buy(count=1, period=7, country="ru", version=Version.IPV6)
except Proxy6APIError as e:
    if e.error_id == 400:
        ...  # low balance
```

### Rate limiting

The API allows **3 requests per second**; over that limit it returns HTTP 429.
The SDK does not throttle for you — wrap calls in your own scheduler if you
fan out widely.

### Using a custom session

Inject any `requests.Session` (e.g. with retry policies or a proxy of your
own):

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504)
)))
client = Proxy6Client(api_key="...", session=session)
```

## Development

```sh
uv sync
uv run pytest
```

## License

MIT
