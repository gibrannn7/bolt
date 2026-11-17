> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.polymarket.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Python SDK

> Get started with the unified Polymarket Python SDK.

The `polymarket-client` package is the official Python SDK for building
Polymarket integrations.

> [card] [GitHub](https://github.com/Polymarket/py-sdk/)
>
> View the Python SDK source.

> [card] [PyPI Package](https://pypi.org/project/polymarket-client/)
>
> Install `polymarket-client` from PyPI.

See the [SDK Changelog](https://docs.polymarket.com/changelog/sdks.md#python) for recent Python releases.

## Quickstart

**1. Install the SDK**

Install the SDK with your preferred package manager.

```bash uv theme={null}
uv add polymarket-client
```

```bash pip theme={null}
pip install polymarket-client
```

```bash poetry theme={null}
poetry add polymarket-client
```

**2. Create a Public Client**

Create an `AsyncPublicClient` to access publicly available Polymarket data.

```python theme={null}
from polymarket import AsyncPublicClient


async with AsyncPublicClient() as client:
    ...
```

**3. Fetch Active Markets**

Fetch a page of active markets to discover trading opportunities.

```python theme={null}
import asyncio

from polymarket import AsyncPublicClient


async def main() -> None:
    async with AsyncPublicClient() as client:
        pages = client.list_markets(closed=False)
        first_page = await pages.first_page()

        for market in first_page.items:
            # market: Market
            ...


asyncio.run(main())
```

## Async and Sync Interfaces

Public clients access public data. [Secure clients](#secure-client) add trading
and account access. Both client types are available in async and sync forms.

| Interface | Public data         | Trading and account data |
| --------- | ------------------- | ------------------------ |
| Async     | `AsyncPublicClient` | `AsyncSecureClient`      |
| Sync      | `PublicClient`      | `SecureClient`           |

Async clients fit services, bots, and applications that already run an event
loop. Sync clients are convenient for scripts and notebooks.

```python Async theme={null}
from polymarket import AsyncPublicClient


async with AsyncPublicClient() as client:
    pages = client.list_markets(closed=False)
    first_page = await pages.first_page()
```

```python Sync theme={null}
from polymarket import PublicClient


with PublicClient() as client:
    pages = client.list_markets(closed=False)
    first_page = pages.first_page()
```

> [!NOTE]
>
> Some features, including realtime subscriptions, are async-only because they
> rely on long-lived streams.

## Pagination

SDK list methods use a consistent paginator interface. Iterate over the
paginator to retrieve every page, or fetch one page at a time when you need to
control pacing.

```python Async theme={null}
pages = client.list_markets(closed=False, page_size=10)

async for page in pages:
    for market in page.items:
        # market: Market
        ...
```

```python Sync theme={null}
pages = client.list_markets(closed=False, page_size=10)

for page in pages:
    for market in page.items:
        # market: Market
        ...
```

When page boundaries do not matter, iterate over every item directly.

```python Async theme={null}
async for market in pages.iter_items():
    # market: Market
    ...
```

```python Sync theme={null}
for market in pages.iter_items():
    # market: Market
    ...
```

`page.next_cursor` is an opaque SDK cursor. Store it as-is if you want to resume
a scan later, and omit it when starting from the first page.

```python Async theme={null}
pages = client.list_markets(closed=False, page_size=10)
page = await pages.first_page()

if page.next_cursor:
    second_page = await pages.from_cursor(page.next_cursor).first_page()
    # second_page.items: tuple[Market, ...]
```

```python Sync theme={null}
pages = client.list_markets(closed=False, page_size=10)
page = pages.first_page()

if page.next_cursor:
    second_page = pages.from_cursor(page.next_cursor).first_page()
    # second_page.items: tuple[Market, ...]
```

## Types

SDK methods return typed models, and their public types are exported from
`polymarket`.

```python theme={null}
from polymarket import Event, Market, OrderBook, PriceHistoryPoint
```

The SDK also uses distinct types for domain identifiers and EVM addresses.
Precision-sensitive values use `decimal.Decimal`, while dates and timestamps
use Python's `datetime` types.

```python theme={null}
from polymarket import ConditionId, EvmAddress, MarketId, PositionId, TokenId
```

## Error Handling

All SDK exceptions inherit from `PolymarketError`. Catch specific exceptions
when your application can respond to them, then catch the base exception as a
fallback.

```python theme={null}
from polymarket import PolymarketError, RateLimitError, UserInputError

pages = client.list_markets(closed=False)

try:
    page = await pages.first_page()
    # page.items: tuple[Market, ...]
except RateLimitError:
    # Retry later.
    ...
except UserInputError:
    # Fix the request parameters.
    ...
except PolymarketError:
    # Handle any other SDK error.
    raise
```

## Secure Client

Create an `AsyncSecureClient` or `SecureClient` when your integration needs to
trade or access account data. The Python SDK creates the signer from a local
private key.

```python Async theme={null}
import os

from polymarket import AsyncSecureClient


async with await AsyncSecureClient.create(
    private_key=os.environ["POLYMARKET_PRIVATE_KEY"],
) as client:
    ...
```

```python Sync theme={null}
import os

from polymarket import SecureClient


with SecureClient.create(
    private_key=os.environ["POLYMARKET_PRIVATE_KEY"],
) as client:
    ...
```

Continue to [Wallets and Authentication](https://docs.polymarket.com/trading/wallets-auth.md) to configure the
account wallet and gasless transactions.

## Realtime Subscriptions

The Python SDK can combine updates from multiple realtime feeds into a single
stream of events.

> [!NOTE]
>
> Realtime subscriptions are available only through `AsyncPublicClient` and
> `AsyncSecureClient`. `PublicClient` and `SecureClient` do not implement
> `subscribe()`.

Call `subscribe()` with one or more subscription specs. Both `AsyncPublicClient`
and `AsyncSecureClient` support public streams, while `AsyncSecureClient` also
provides private streams for the connected account.

```python Public Client theme={null}
from polymarket.streams import MarketSpec, SportsSpec

asset_id = "<asset_id>"

async with await client.subscribe(
    [MarketSpec(asset_ids=[asset_id]), SportsSpec()],
) as stream:
    async for event in stream:
        # event:
        #   MarketBookEvent
        #   | MarketPriceChangeEvent
        #   | MarketLastTradePriceEvent
        #   | MarketTickSizeChangeEvent
        #   | MarketBestBidAskEvent
        #   | NewMarketEvent
        #   | MarketResolvedEvent
        #   | SportsEvent

        if should_close:
            break
```

```python Secure Client theme={null}
from polymarket.streams import MarketSpec, UserSpec

asset_id = "<asset_id>"

async with await client.subscribe(
    [MarketSpec(asset_ids=[asset_id]), UserSpec()],
) as stream:
    async for event in stream:
        # event:
        #   MarketBookEvent
        #   | MarketPriceChangeEvent
        #   | MarketLastTradePriceEvent
        #   | MarketTickSizeChangeEvent
        #   | MarketBestBidAskEvent
        #   | NewMarketEvent
        #   | MarketResolvedEvent
        #   | UserEvent

        if should_close:
            break
```

Narrow `event.topic` before handling a specific event shape. The examples show
a few streams; see [Real-Time Data](https://docs.polymarket.com/market-data/realtime-data.md),
[Real-Time Order Updates](https://docs.polymarket.com/trading/realtime-order-updates.md), and
[Perps Realtime Updates](https://docs.polymarket.com/perps/realtime-updates.md) for feed-specific options.

## DataFrames and Jupyter

Convert pages and paginators directly to a
[pandas DataFrame](https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.html),
[Polars DataFrame](https://docs.pola.rs/py-polars/html/reference/dataframe/), or
[Apache Arrow Table](https://arrow.apache.org/docs/python/generated/pyarrow.Table.html).
Install the `pandas`, `polars`, or `arrow` package extra for the format you use;
the `quant` extra installs all three.

```python Pandas theme={null}
pages = client.list_markets(closed=False)
df = await pages.to_pandas(limit=100)
```

```python Polars theme={null}
pages = client.list_markets(closed=False)
df = await pages.to_polars(limit=100)
```

```python Arrow theme={null}
pages = client.list_markets(closed=False)
table = await pages.to_arrow(limit=100)
```

Paginator conversions require an explicit limit. Pass `limit=None` to retrieve
every item.

Common SDK objects also render as compact cards in
[Jupyter](https://docs.jupyter.org/en/stable/) notebooks. Return an object as
the last expression in a cell to display it.

```python theme={null}
pages = client.list_markets(closed=False)
page = await pages.first_page()
page.items[0]
```

## Next Steps

> [card] [Read Market Data](https://docs.polymarket.com/market-data/overview.md)
>
> Discover markets and work with prices, order books, and historical data.

> [card] [Subscribe to Real-Time Updates](https://docs.polymarket.com/market-data/realtime-data.md)
>
> Stream market and account updates as they happen.

> [card] [Place Your First Order](https://docs.polymarket.com/trading/quickstart.md)
>
> Set up an account and complete your first authenticated trade.

> [card] [Use Session Keys](https://docs.polymarket.com/trading/session-keys.md)
>
> Grant scoped, time-limited Deposit Wallet access to a separate signer.

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.

> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.polymarket.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Discover Markets

> Learn how to find and filter events and markets and explore related metadata.

Find the events and markets your integration needs, from a specific Polymarket link to a broader view of what is active. This data is public and does not require authentication.

## Events

An event groups one or more markets under a shared question set. A single-market event asks one yes/no question; a multi-market event splits a broader question into individual outcomes, such as one market per candidate in an election.

### Fetch an Event

Fetch an event when you already know its identifier.

> [tab] TypeScript
>
> Call `fetchEvent()` on a `PublicClient` or `SecureClient` to fetch an event by ID.
>
> ```ts theme={null}
> const event = await client.fetchEvent({ id: "90177" });
>
> // event: Event
> ```
>
> You can also fetch an event by its Polymarket URL or slug:
>
> ```ts URL theme={null}
> const event = await client.fetchEvent({
>   url: "https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-before-2027",
> });
> ```
>
> ```ts Slug theme={null}
> const event = await client.fetchEvent({
>   slug: "will-the-us-confirm-that-aliens-exist-before-2027",
> });
> ```
>
> > [accordion] Output: Event
> >
> > ```ts Event Type theme={null}
> > type Market = {
> >   id: string;
> >   version?: ProtocolVersion | null;
> >   slug?: string | null;
> >   question?: string | null;
> >   conditionId: ConditionId | null;
> >   outcomes: {
> >     yes: { tokenId: TokenId | null; positionId: PositionId | null };
> >     no: { tokenId: TokenId | null; positionId: PositionId | null };
> >   };
> > };
> >
> > type Event = {
> >   id: string;
> >   slug?: string | null;
> >   title?: string | null;
> >   markets: Market[];
> > };
> > ```
> >
> > ```json Event Example (Polymarket V2) theme={null}
> > {
> >   "id": "<event_id>",
> >   "slug": "<event_slug>",
> >   "title": "<event_title>",
> >   "markets": [
> >     {
> >       "id": "1",
> >       "version": "v2",
> >       "slug": "<market_slug>",
> >       "question": "<market_question>",
> >       "conditionId": "0x017089ce3ba22aaa0a4cba8250b8c8e1eb0000000000000000000000000000",
> >       "outcomes": {
> >         "yes": {
> >           "tokenId": null,
> >           "positionId": "651150819117105875331414918119047680898421632356043490229292782433651916800"
> >         },
> >         "no": {
> >           "tokenId": null,
> >           "positionId": "651150819117105875331414918119047680898421632356043490229292782433651916801"
> >         }
> >       }
> >     }
> >   ]
> > }
> > ```
> >
> > ```json Event Example (CTF) theme={null}
> > {
> >   "id": "90177",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >   "title": "Will the US confirm that aliens exist by...?",
> >   "markets": [
> >     {
> >       "id": "703257",
> >       "version": "v1",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >       "question": "Will the US confirm that aliens exist before 2027?",
> >       "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >       "outcomes": {
> >         "yes": {
> >           "tokenId": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
> >           "positionId": null
> >         },
> >         "no": {
> >           "tokenId": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
> >           "positionId": null
> >         }
> >       }
> >     },
> >     "..."
> >   ]
> > }
> > ```

> [tab] Python
>
> Call `get_event()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch an event by ID.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> event = await client.get_event(id="90177")
>
> # event: Event
> ```
>
> You can also fetch an event by its Polymarket URL or slug:
>
> ```python URL theme={null}
> event = await client.get_event(
>     url="https://polymarket.com/event/will-the-us-confirm-that-aliens-exist-before-2027",
> )
> ```
>
> ```python Slug theme={null}
> event = await client.get_event(
>     slug="will-the-us-confirm-that-aliens-exist-before-2027",
> )
> ```
>
> > [accordion] Output: Event
> >
> > ```python Event Type theme={null}
> > class MarketOutcome:
> >     token_id: TokenId | None
> >     position_id: PositionId | None
> >
> > class MarketOutcomes:
> >     yes: MarketOutcome
> >     no: MarketOutcome
> >
> > class Market:
> >     id: str
> >     version: ProtocolVersion | None
> >     slug: str | None
> >     question: str | None
> >     condition_id: ConditionId | None
> >     outcomes: MarketOutcomes
> >
> > class Event:
> >     id: str
> >     slug: str | None
> >     title: str | None
> >     markets: tuple[Market, ...]
> > ```
> >
> > ```json Event Example (Polymarket V2) theme={null}
> > {
> >   "id": "<event_id>",
> >   "slug": "<event_slug>",
> >   "title": "<event_title>",
> >   "markets": [
> >     {
> >       "id": "1",
> >       "version": "v2",
> >       "slug": "<market_slug>",
> >       "question": "<market_question>",
> >       "condition_id": "0x017089ce3ba22aaa0a4cba8250b8c8e1eb0000000000000000000000000000",
> >       "outcomes": {
> >         "yes": {
> >           "token_id": null,
> >           "position_id": "651150819117105875331414918119047680898421632356043490229292782433651916800"
> >         },
> >         "no": {
> >           "token_id": null,
> >           "position_id": "651150819117105875331414918119047680898421632356043490229292782433651916801"
> >         }
> >       }
> >     }
> >   ]
> > }
> > ```
> >
> > ```json Event Example (CTF) theme={null}
> > {
> >   "id": "90177",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >   "title": "Will the US confirm that aliens exist by...?",
> >   "markets": [
> >     {
> >       "id": "703257",
> >       "version": "v1",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >       "question": "Will the US confirm that aliens exist before 2027?",
> >       "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >       "outcomes": {
> >         "yes": {
> >           "token_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
> >           "position_id": null
> >         },
> >         "no": {
> >           "token_id": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
> >           "position_id": null
> >         }
> >       }
> >     },
> >     "..."
> >   ]
> > }
> > ```

> [tab] API
>
> Fetch an event by ID:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/90177"
> ```
>
> You can also fetch an event by slug:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/slug/will-the-us-confirm-that-aliens-exist-before-2027"
> ```
>
> > [accordion] Output: Event
> >
> > ```ts Event Type theme={null}
> > type Market = {
> >   id: string;
> >   version: string | null;
> >   slug: string;
> >   question: string | null;
> >   conditionId: string | null;
> >   clobTokenIds: string | null;
> >   positionIds: string[] | null;
> > };
> >
> > type Event = {
> >   id: string;
> >   slug: string | null;
> >   title: string | null;
> >   markets: Market[];
> > };
> > ```
> >
> > ```json Event Example (Polymarket V2) theme={null}
> > {
> >   "id": "<event_id>",
> >   "slug": "<event_slug>",
> >   "title": "<event_title>",
> >   "markets": [
> >     {
> >       "id": "1",
> >       "version": "v2",
> >       "slug": "<market_slug>",
> >       "question": "<market_question>",
> >       "conditionId": "0x017089ce3ba22aaa0a4cba8250b8c8e1eb0000000000000000000000000000",
> >       "clobTokenIds": null,
> >       "positionIds": [
> >         "651150819117105875331414918119047680898421632356043490229292782433651916800",
> >         "651150819117105875331414918119047680898421632356043490229292782433651916801"
> >       ]
> >     }
> >   ]
> > }
> > ```
> >
> > ```json Event Example (CTF) theme={null}
> > {
> >   "id": "90177",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >   "title": "Will the US confirm that aliens exist by...?",
> >   "markets": [
> >     {
> >       "id": "703257",
> >       "version": "v1",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >       "question": "Will the US confirm that aliens exist before 2027?",
> >       "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >       "clobTokenIds": "[\"107505882767731489358349912513945399560393482969656700824895970500493757150417\",\"7305630249804085635496399869905769372294302716159034447326228509068694952392\"]",
> >       "positionIds": null
> >     },
> >     "..."
> >   ]
> > }
> > ```

### List Events

List events when you need a browsable or filterable feed.

> [tab] TypeScript
>
> Call `listEvents()` on a `PublicClient` or `SecureClient` to page through events.
>
> ```ts theme={null}
> const pages = client.listEvents({ closed: false, pageSize: 20 });
>
> for await (const page of pages) {
>   // page.items: Event[]
> }
> ```
>
> > [accordion] Output: Event\[]
> >
> > ```ts Page Type theme={null}
> > type Market = {
> >   id: string;
> >   slug?: string | null;
> >   question?: string | null;
> >   conditionId: string | null;
> > };
> >
> > type Event = {
> >   id: string;
> >   slug?: string | null;
> >   title?: string | null;
> >   markets: Market[];
> > };
> >
> > type Page = {
> >   items: Event[];
> >   hasMore: boolean;
> >   nextCursor?: string;
> > };
> > ```
> >
> > ```json Page Example theme={null}
> > {
> >   "items": [
> >     {
> >       "id": "16183",
> >       "slug": "kraken-ipo-in-2025",
> >       "title": "Kraken IPO by ___ ?",
> >       "markets": [
> >         {
> >           "id": "516950",
> >           "slug": "kraken-ipo-in-2025",
> >           "question": "Kraken IPO in 2025?"
> >         },
> >         "..."
> >       ]
> >     },
> >     {
> >       "id": "16263",
> >       "slug": "macron-out-in-2025",
> >       "title": "Macron out by...?",
> >       "markets": ["..."]
> >     },
> >     "..."
> >   ],
> >   "hasMore": true,
> >   "nextCursor": "9YTr9qyfU9571U9_leL7LNSWUI6EXd7rpAqdh-EbPr17InYiOjEsImsiOiJldmVudHMiLCJvaCI6IjRmNTNjZGExOGMyYmFhMGMwMzU0YmI1ZjlhM2VjYmU1ZWQxMmFiNGQ4ZTExYmE4NzNjMmYxMTE2MTIwMmI5NDUiLCJrZXlzIjpbeyJ0Ijoic3RyaW5nIiwidiI6IjI1ODE1In1dfQ"
> > }
> > ```
>
> Filter by tag by passing one or more numeric tag IDs:
>
> ```ts theme={null}
> const pages = client.listEvents({
>   tagIds: [745], // numeric ID for the "nba" tag; see Tags below to look these up
>   closed: false,
> });
>
> for await (const page of pages) {
>   // page.items: Event[]
> }
> ```

> [tab] Python
>
> Call `list_events()` on an `AsyncPublicClient` or `AsyncSecureClient` to page through events.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> pages = client.list_events(closed=False, page_size=20)
>
> async for page in pages:
>     ...  # page.items: tuple[Event, ...]
> ```
>
> > [accordion] Output: Event\[]
> >
> > ```python Page Type theme={null}
> > class Market:
> >     id: str
> >     slug: str | None
> >     question: str | None
> >     condition_id: str | None
> >
> > class Event:
> >     id: str
> >     slug: str | None
> >     title: str | None
> >     markets: tuple[Market, ...]
> >
> > class Page:
> >     items: tuple[Event, ...]
> >     has_more: bool
> >     next_cursor: str | None
> > ```
> >
> > ```json Page Example theme={null}
> > {
> >   "items": [
> >     {
> >       "id": "16183",
> >       "slug": "kraken-ipo-in-2025",
> >       "title": "Kraken IPO by ___ ?"
> >     },
> >     {
> >       "id": "16263",
> >       "slug": "macron-out-in-2025",
> >       "title": "Macron out by...?"
> >     },
> >     "..."
> >   ],
> >   "has_more": true,
> >   "next_cursor": "eyJmIjoiYWQyZjRkNmY4ZDZkIiwiayI6IjlZVHI5cXlmVTk1NzFVOV9sZUw3TE5TV1VJNkVYZDdycEFxZGgtRWJQcjE3SW5ZaU9qRXNJbXNpT2lKbGRtVnVkSE1pTENKdmFDSTZJalJtTlROalpHRXhPR015WW1GaE1HTXdNelUwWW1JMVpqbGhNMlZqWW1VMVpXUXhNbUZpTkdRNFpURXhZbUU0TnpOak1tWXhNVEUyTVRJd01tSTVORFVpTENKclpYbHpJanBiZXlKMElqb2ljM1J5YVc1bklpd2lkaUk2SWpJMU9ERTFJbjFkZlEiLCJwIjoiL2V2ZW50cy9rZXlzZXQiLCJzdmMiOiJnYW1tYSIsInYiOjF9"
> > }
> > ```
>
> Filter by tag by passing a numeric tag ID:
>
> ```python theme={null}
> pages = client.list_events(
>     tag_ids=[745],  # numeric ID for the "nba" tag; see Tags below to look these up
>     closed=False,
> )
>
> async for page in pages:
>     ...  # page.items: tuple[Event, ...]
> ```

> [tab] API
>
> List active events:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?closed=false&limit=20"
> ```
>
> > [accordion] Output: Events Page
> >
> > ```json Example theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "16183",
> >       "slug": "kraken-ipo-in-2025",
> >       "title": "Kraken IPO by ___ ?"
> >     },
> >     "..."
> >   ],
> >   "next_cursor": "9YTr9qyfU9571U9_leL7LNSWUI6EXd7rpAqdh-EbPr17InYiOjEsImsiOiJldmVudHMiLCJvaCI6IjRmNTNjZGExOGMyYmFhMGMwMzU0YmI1ZjlhM2VjYmU1ZWQxMmFiNGQ4ZTExYmE4NzNjMmYxMTE2MTIwMmI5NDUiLCJrZXlzIjpbeyJ0Ijoic3RyaW5nIiwidiI6IjI1ODE1In1dfQ"
> > }
> > ```
>
> Pass `next_cursor` as `after_cursor` to fetch the next page:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?closed=false&limit=20&after_cursor=<next_cursor>"
> ```
>
> Filter by tag with `tag_id`:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?tag_id=745&closed=false&limit=20"
> ```
>
> On `GET /events` and `GET /events/keyset`, omitting `closed` returns open and closed events. `closed=true` selects closed events and `closed=false` selects open events. `closed=any` (case-insensitive) also includes both states, with no identifier filter required.

### Filter Events by Protocol

Select events for the position system your integration handles.

> [tab] TypeScript
>
> Call `listEvents()` on an existing `PublicClient` or `SecureClient`.
> If needed, [create a Public Client](https://docs.polymarket.com/getting-started/typescript.md#create-a-public-client) first.
>
> ```ts theme={null}
> import { ProtocolVersion } from "@polymarket/client";
>
> const pages = client.listEvents({
>   version: ProtocolVersion.V2,
>   closed: false,
>   pageSize: 20,
> });
>
> for await (const page of pages) {
>   // page.items: Event[]
> }
> ```
>
> Use `ProtocolVersion.V2` for Polymarket Protocol V2 events or
> `ProtocolVersion.V1` for CTF events. To include both, pass
> `version: [ProtocolVersion.V1, ProtocolVersion.V2]`. Arrays accept one or
> two values. Omission uses the current server default of CTF events (v1).
> The paginator keeps the
> filter on subsequent pages. When resuming with `cursor`, pass the same
> `version`.

> [tab] Python
>
> Call `list_events()` on an existing `AsyncPublicClient` or
> `AsyncSecureClient`. If needed,
> [create a Public Client](https://docs.polymarket.com/getting-started/python.md#create-a-public-client) first.
> Sync clients expose the same option.
>
> ```python theme={null}
> pages = client.list_events(version="v2", closed=False, page_size=20)
>
> async for page in pages:
>     # page.items: tuple[Event, ...]
>     pass
> ```
>
> Use `version="v2"` for Polymarket Protocol V2 events or `version="v1"`
> for CTF events. To include both, pass `version=["v1", "v2"]`. The option
> accepts a string, a `ProtocolVersion` enum value, or a sequence of one or
> two values. Omission or `None` uses the current server default of CTF
> events (v1). The paginator keeps the filter on subsequent pages. To resume,
> create `pages` with the same `version` and other filters, then continue
> with the paginator returned by `pages.from_cursor(saved_cursor)`.

> [tab] API
>
> List Polymarket Protocol V2 events:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?version=v2&closed=false&limit=20"
> ```
>
> Illustrative response (fields trimmed):
>
> > [accordion] Output: Events Page
> >
> > ```json theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "12345",
> >       "slug": "example-v2-event",
> >       "title": "Example Protocol V2 Event"
> >     }
> >   ],
> >   "next_cursor": "<next_cursor>"
> > }
> > ```
>
> Use `version=v1` for CTF events. Repeat the parameter as
> `version=v1&version=v2` to include both. Each value must be `v1` or `v2`,
> with at most two values. Omission uses the current server default of CTF
> events (v1).
> Continue with `next_cursor` as `after_cursor`, keeping the same `version`
> and other filters:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?version=v2&closed=false&limit=20&after_cursor=<next_cursor>"
> ```

## Markets

A market is a single yes/no question with two outcome IDs, one for YES
and one for NO.

### Fetch a Market

Fetch a market when you already know its identifier.

> [tab] TypeScript
>
> Call `fetchMarket()` on a `PublicClient` or `SecureClient` to fetch a market by ID.
>
> ```ts theme={null}
> const market = await client.fetchMarket({ id: "703257" });
>
> // market: Market
> ```
>
> You can also fetch a market by its Polymarket URL or slug:
>
> ```ts URL theme={null}
> const market = await client.fetchMarket({
>   url: "https://polymarket.com/market/will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> });
> ```
>
> ```ts Slug theme={null}
> const market = await client.fetchMarket({
>   slug: "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> });
> ```
>
> > [accordion] Output: Market
> >
> > ```ts Market Type theme={null}
> > type Market = {
> >   id: string;
> >   version?: ProtocolVersion | null;
> >   slug?: string | null;
> >   question?: string | null;
> >   conditionId: ConditionId | null;
> >   outcomes: {
> >     yes: { tokenId: TokenId | null; positionId: PositionId | null };
> >     no: { tokenId: TokenId | null; positionId: PositionId | null };
> >   };
> > };
> > ```
> >
> > ```json Market Example theme={null}
> > {
> >   "id": "703257",
> >   "version": "v1",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >   "question": "Will the US confirm that aliens exist before 2027?",
> >   "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >   "outcomes": {
> >     "yes": {
> >       "tokenId": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
> >       "positionId": null
> >     },
> >     "no": {
> >       "tokenId": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
> >       "positionId": null
> >     }
> >   }
> > }
> > ```

> [tab] Python
>
> Call `get_market()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch a market by ID.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> market = await client.get_market(id="703257")
>
> # market: Market
> ```
>
> You can also fetch a market by its Polymarket URL or slug:
>
> ```python URL theme={null}
> market = await client.get_market(
>     url="https://polymarket.com/market/will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> )
> ```
>
> ```python Slug theme={null}
> market = await client.get_market(
>     slug="will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> )
> ```
>
> > [accordion] Output: Market
> >
> > ```python Market Type theme={null}
> > class MarketOutcome:
> >     token_id: TokenId | None
> >     position_id: PositionId | None
> >
> > class MarketOutcomes:
> >     yes: MarketOutcome
> >     no: MarketOutcome
> >
> > class Market:
> >     id: str
> >     version: ProtocolVersion | None
> >     slug: str | None
> >     question: str | None
> >     condition_id: ConditionId | None
> >     outcomes: MarketOutcomes
> > ```
> >
> > ```json Market Example theme={null}
> > {
> >   "id": "703257",
> >   "version": "v1",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >   "question": "Will the US confirm that aliens exist before 2027?",
> >   "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >   "outcomes": {
> >     "yes": {
> >       "token_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
> >       "position_id": null
> >     },
> >     "no": {
> >       "token_id": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
> >       "position_id": null
> >     }
> >   }
> > }
> > ```

> [tab] API
>
> Fetch a market by ID:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/703257"
> ```
>
> You can also fetch a market by slug:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/slug/will-the-us-confirm-that-aliens-exist-before-2027-789-924-249"
> ```
>
> > [accordion] Output: Market
> >
> > ```json Example theme={null}
> > {
> >   "id": "703257",
> >   "version": "v1",
> >   "slug": "will-the-us-confirm-that-aliens-exist-before-2027-789-924-249",
> >   "question": "Will the US confirm that aliens exist before 2027?",
> >   "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
> >   "clobTokenIds": "[\"107505882767731489358349912513945399560393482969656700824895970500493757150417\",\"7305630249804085635496399869905769372294302716159034447326228509068694952392\"]",
> >   "positionIds": null
> > }
> > ```

### List Markets

List markets when you need a filterable feed, such as browsing by tag, sport, or liquidity.

> [tab] TypeScript
>
> Call `listMarkets()` on a `PublicClient` or `SecureClient` to page through markets.
>
> ```ts theme={null}
> const pages = client.listMarkets({
>   tagId: 745, // numeric ID for the "nba" tag; see Tags below to look these up
>   closed: false,
>   pageSize: 20,
> });
>
> for await (const page of pages) {
>   // page.items: Market[]
> }
> ```
>
> > [accordion] Output: Market\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": "741099",
> >     "slug": "will-lebron-james-retire-before-next-nba-season",
> >     "question": "Will LeBron James retire before next NBA season?",
> >     "conditionId": "0x73057b771600660ac6e659c5b831587fd3bdd378e63f359731aa3e1538577fb0"
> >   },
> >   {
> >     "id": "1747460",
> >     "slug": "will-giannis-antetokounmpo-play-for-the-atlanta-hawks-in-2026-27",
> >     "question": "Will Giannis Antetokounmpo play for the Atlanta Hawks in 2026-27?",
> >     "conditionId": "0xff2715084bb2cf20d9b88b74ef809c3317b1e99f6c006faee9b83bc85aa0fc99"
> >   },
> >   "..."
> > ]
> > ```

> [tab] Python
>
> Call `list_markets()` on an `AsyncPublicClient` or `AsyncSecureClient` to page through markets.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> pages = client.list_markets(
>     tag_id=745,  # numeric ID for the "nba" tag; see Tags below to look these up
>     closed=False,
>     page_size=20,
> )
>
> async for page in pages:
>     ...  # page.items: tuple[Market, ...]
> ```
>
> > [accordion] Output: Market\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": "741099",
> >     "slug": "will-lebron-james-retire-before-next-nba-season",
> >     "question": "Will LeBron James retire before next NBA season?",
> >     "condition_id": "0x73057b771600660ac6e659c5b831587fd3bdd378e63f359731aa3e1538577fb0"
> >   },
> >   {
> >     "id": "1747460",
> >     "slug": "will-giannis-antetokounmpo-play-for-the-atlanta-hawks-in-2026-27",
> >     "question": "Will Giannis Antetokounmpo play for the Atlanta Hawks in 2026-27?",
> >     "condition_id": "0xff2715084bb2cf20d9b88b74ef809c3317b1e99f6c006faee9b83bc85aa0fc99"
> >   },
> >   "..."
> > ]
> > ```

> [tab] API
>
> List active markets by tag:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/keyset?tag_id=745&closed=false&limit=20"
> ```
>
> > [accordion] Output: Markets Page
> >
> > ```json Example theme={null}
> > {
> >   "markets": [
> >     {
> >       "id": "540817",
> >       "slug": "new-rhianna-album-before-gta-vi-926",
> >       "question": "New Rihanna Album before GTA VI?",
> >       "conditionId": "0x1fad72fae204143ff1c3035e99e7c0f65ea8d5cd9bd1070987bd1a3316f772be"
> >     },
> >     "..."
> >   ],
> >   "next_cursor": "8ejWEAtEdA8gG05m-tRMeLtBDl1Wbw1fUbXVfm0eYSZ7InYiOjEsImsiOiJtYXJrZXRzIiwib2giOiI0ZjUzY2RhMThjMmJhYTBjMDM1NGJiNWY5YTNlY2JlNWVkMTJhYjRkOGUxMWJhODczYzJmMTExNjEyMDJiOTQ1Iiwia2V5cyI6W3sidCI6InN0cmluZyIsInYiOiI1NTg5NDAifV19"
> > }
> > ```
>
> Pass `next_cursor` as `after_cursor` to fetch the next page:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/keyset?tag_id=745&closed=false&limit=20&after_cursor=<next_cursor>"
> ```
>
> To look up markets without knowing whether they are open or closed, pass an identifier and `closed=any`:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/keyset?id=540817&closed=any&limit=20"
> ```
>
> On `GET /markets` and `GET /markets/keyset`, omitted `closed` and `closed=false` return open markets; `closed=true` selects closed markets. `closed=any` (case-insensitive) removes that filter and requires at least one of `id`, `slug`, `clob_token_ids`, `position_ids`, `condition_ids`, `request_ids`, `onchain_event_ids`, or `question_ids`. Each identifier filter accepts at most 100 values. Other filters still apply.
>
> `closed=any` without an identifier, including a request with only `tag_id`, returns HTTP 422. An invalid `closed` value also returns HTTP 422.

After you choose a market, continue to [Market Details](https://docs.polymarket.com/market-data/market-details.md)
to select its outcome IDs and trading fields.

### Find Markets by Oracle Request

Use a known oracle request or on-chain event to find related Polymarket Protocol
V2 markets, or filter by their resolution state when building a settlement view.

> [tab] TypeScript
>
> Call `listMarkets()` on a `PublicClient` or `SecureClient`. Start with the
> resolution state you want to follow.
>
> ```ts theme={null}
> import { MarketResolutionStatus, ProtocolVersion } from "@polymarket/client";
>
> const pages = client.listMarkets({
>   version: ProtocolVersion.V2,
>   resolutionStatus: MarketResolutionStatus.Active,
> });
>
> for await (const page of pages) {
>   for (const market of page.items) {
>     console.log(
>       market.resolution.requestId,
>       market.resolution.onchainEventId,
>       market.resolution.resolutionStatus,
>     );
>   }
> }
> ```
>
> To query both protocols, omit the resolution-state filter and pass
> `version: [ProtocolVersion.V1, ProtocolVersion.V2]`.
> `version` accepts one value or an array of one or two values. Omission uses the
> current server default of CTF markets (v1). Keep the same selection when resuming
> a cursor.
>
> `requestId` is the bytes32 oracle key. `onchainEventId` is the parent bytes32
> on-chain event ID with its bottom three bytes zero. Both, and `resolutionStatus`,
> can be `null` or absent when metadata is unavailable.
>
> To narrow a subsequent read, pass `requestIds: [requestId]` or
> `onchainEventIds: [onchainEventId]` when you have a returned non-null ID. Each
> filter accepts at most 100 values and is retained across pages.

> [tab] Python
>
> Call `list_markets()` on an `AsyncPublicClient` or `AsyncSecureClient`.
> The synchronous clients provide the same filters.
>
> ```python theme={null}
> pages = client.list_markets(version="v2", resolution_status="active")
>
> async for page in pages:
>     for market in page.items:
>         print(
>             market.resolution.request_id,
>             market.resolution.onchain_event_id,
>             market.resolution.resolution_status,
>         )
> ```
>
> To query both protocols, omit the resolution-state filter and pass
> `version=["v1", "v2"]`. `version` accepts one
> string or enum value, or a sequence of one or two values. Omission or `None` uses
> the current server default of CTF markets (v1). Keep the same selection when
> resuming with `pages.from_cursor(saved_cursor)`.
>
> `request_id` is the bytes32 oracle key. `onchain_event_id` is the parent bytes32
> on-chain event ID with its bottom three bytes zero. Both, and
> `resolution_status`, are `None` when metadata is unavailable.
>
> To narrow a subsequent read, pass `request_ids=[request_id]` or
> `onchain_event_ids=[onchain_event_id]` when you have a returned non-`None` ID.
> Each filter accepts at most 100 values and is retained across pages.

> [tab] API
>
> Filter the market collection by protocol version and resolution state.
>
> ```bash theme={null}
> curl -G "https://gamma-api.polymarket.com/markets/keyset" \
>   --data-urlencode "version=v2" \
>   --data-urlencode "resolution_status=active"
> ```
>
> Illustrative response (fields trimmed):
>
> > [accordion] Output: Markets Page
> >
> > ```json theme={null}
> > {
> >   "markets": [
> >     {
> >       "id": "12345",
> >       "slug": "example-v2-market",
> >       "question": "Will Team A win?",
> >       "version": "v2",
> >       "requestId": "0xcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd00",
> >       "onchainEventId": "0xababababababababababababababababababababababababababababab000000",
> >       "resolutionStatus": "active"
> >     }
> >   ],
> >   "next_cursor": "<next_cursor>"
> > }
> > ```
>
> Omit `resolution_status` and repeat `version` as `version=v1&version=v2` to
> query both protocols. Each
> value must be `v1` or `v2`, with at most two values. Omission uses the current
> server default of CTF markets (v1). Keep the same selection when continuing with
> `after_cursor`.
>
> Response markets can include `requestId`, `onchainEventId`, and
> `resolutionStatus`. `requestId` is the bytes32 oracle key. `onchainEventId` is
> the parent bytes32 on-chain event ID with its bottom three bytes zero.
>
> Filter by a known ID with `request_ids=<request_id>` or
> `onchain_event_ids=<onchain_event_id>`. Repeat the query parameter for multiple
> IDs, up to 100 per filter, and preserve these filters when continuing with
> `after_cursor`.

The resolution states are `inactive` (drafted, not deployed on chain), `active`
(deployed, unresolved), and `resolved`. This state belongs to Polymarket
Protocol V2 markets. CTF markets retain their UMA resolution status.
An oracle request identifies one binary or incremental neg-risk market by its
condition ID, or an atomic neg-risk event by its on-chain event ID. Markets in
one on-chain event share the parent event ID.

## Series

A series groups a recurring set of events under one theme. For example, a weekly Fed rate-decision series has one event per meeting, and a season-long league series has one event per matchup.

### Fetch a Series

Fetch a series by ID.

> [tab] TypeScript
>
> Call `fetchSeries()` on a `PublicClient` or `SecureClient` to fetch a series by ID.
>
> ```ts theme={null}
> const series = await client.fetchSeries({ id: "1" });
>
> // series: Series
> ```
>
> > [accordion] Output: Series
> >
> > ```json Example theme={null}
> > {
> >   "id": "1",
> >   "slug": "nfl",
> >   "title": "NFL",
> >   "recurrence": "weekly",
> >   "closed": false
> > }
> > ```

> [tab] Python
>
> Call `get_series()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch a series by ID.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> series = await client.get_series("1")
>
> # series: Series
> ```
>
> > [accordion] Output: Series
> >
> > ```json Example theme={null}
> > {
> >   "id": "1",
> >   "slug": "nfl",
> >   "title": "NFL",
> >   "recurrence": "weekly",
> >   "closed": false
> > }
> > ```

> [tab] API
>
> Fetch a series by ID:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/series/1"
> ```
>
> > [accordion] Output: Series
> >
> > ```json Example theme={null}
> > {
> >   "id": "1",
> >   "slug": "nfl",
> >   "title": "NFL",
> >   "recurrence": "weekly",
> >   "closed": false
> > }
> > ```

### List Series

> [tab] TypeScript
>
> Call `listSeries()` on a `PublicClient` or `SecureClient` to page through series.
>
> ```ts theme={null}
> const pages = client.listSeries({
>   recurrence: "weekly",
>   closed: false,
>   pageSize: 20,
> });
>
> for await (const page of pages) {
>   // page.items: Series[]
> }
> ```
>
> > [accordion] Output: Series\[]
> >
> > ```json Example theme={null}
> > [
> >   { "id": "1", "slug": "nfl", "title": "NFL" },
> >   { "id": "2", "slug": "nba", "title": "NBA" },
> >   { "id": "3", "slug": "mlb", "title": "MLB" },
> >   "..."
> > ]
> > ```

> [tab] Python
>
> Call `list_series()` on an `AsyncPublicClient` or `AsyncSecureClient` to page through series.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> pages = client.list_series(
>     recurrence="weekly",
>     closed=False,
>     page_size=20,
> )
>
> async for page in pages:
>     ...  # page.items: tuple[Series, ...]
> ```
>
> > [accordion] Output: Series\[]
> >
> > ```json Example theme={null}
> > [
> >   { "id": "1", "slug": "nfl", "title": "NFL" },
> >   { "id": "2", "slug": "nba", "title": "NBA" },
> >   { "id": "3", "slug": "mlb", "title": "MLB" },
> >   "..."
> > ]
> > ```

> [tab] API
>
> List active weekly series:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/series?recurrence=weekly&closed=false&limit=20"
> ```
>
> > [accordion] Output: Series\[]
> >
> > ```json Example theme={null}
> > [
> >   { "id": "1", "slug": "nfl", "title": "NFL" },
> >   { "id": "2", "slug": "nba", "title": "NBA" },
> >   { "id": "3", "slug": "mlb", "title": "MLB" },
> >   "..."
> > ]
> > ```

## Sports

Sports metadata maps a sport to its Polymarket tags and market types. Use it to browse sports markets by league, look up the valid market types for filtering, find events associated with a game, or resolve team rosters.

### List Sports

> [tab] TypeScript
>
> Call `listSports()` on a `PublicClient` or `SecureClient` to list supported sports.
>
> ```ts theme={null}
> const sports = await client.listSports();
>
> // sports: SportsMetadata[]
> ```
>
> > [accordion] Output: SportsMetadata\[]
> >
> > ```json Example theme={null}
> > [
> >   { "id": 1, "sport": "ncaab", "tags": "1,100149,100639" },
> >   { "id": 2, "sport": "epl", "tags": "1,82,306,100639,100350" },
> >   { "id": 3, "sport": "lal", "tags": "1,780,100639,100350" }
> > ]
> > ```

> [tab] Python
>
> Call `get_sports()` on an `AsyncPublicClient` or `AsyncSecureClient` to list supported sports.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> sports = await client.get_sports()
>
> # sports: tuple[SportsMetadata, ...]
> ```
>
> > [accordion] Output: SportsMetadata\[]
> >
> > ```json Example theme={null}
> > [
> >   { "id": 1, "sport": "ncaab", "tags": "1,100149,100639" },
> >   { "id": 2, "sport": "epl", "tags": "1,82,306,100639,100350" },
> >   { "id": 3, "sport": "lal", "tags": "1,780,100639,100350" }
> > ]
> > ```

> [tab] API
>
> List supported sports:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/sports"
> ```
>
> > [accordion] Output: SportsMetadata\[]
> >
> > ```json Example theme={null}
> > [
> >   { "sport": "ncaab", "tags": "1,100149,100639" },
> >   { "sport": "epl", "tags": "1,82,306,100639,100350" },
> >   { "sport": "lal", "tags": "1,780,100639,100350" }
> > ]
> > ```

### Sports Market Types

Every sports market carries a market type that tells you which line it prices: a moneyline (which team wins), a spread (win by how much), or a total (over/under a combined score). Fetch the valid values, then pass one or more of them when listing markets to filter.

> [tab] TypeScript
>
> Call `fetchSportsMarketTypes()` on a `PublicClient` or `SecureClient` to list the
> supported market types. When present, a market reports its type in
> `sports.sportsMarketType`.
>
> ```ts theme={null}
> const { marketTypes } = await client.fetchSportsMarketTypes();
>
> // marketTypes: string[]
> ```
>
> > [accordion] Output: string\[]
> >
> > ```json Example theme={null}
> > {
> >   "marketTypes": ["moneyline", "spreads", "totals"]
> > }
> > ```
>
> Filter markets by type:
>
> ```ts theme={null}
> const pages = client.listMarkets({
>   sportsMarketTypes: ["spreads"],
>   closed: false,
>   pageSize: 20,
> });
>
> for await (const page of pages) {
>   // page.items: Market[]
> }
> ```

> [tab] Python
>
> Call `get_sports_market_types()` on an `AsyncPublicClient` or
> `AsyncSecureClient` to list the supported market types. The synchronous
> `PublicClient` and `SecureClient` provide the same method. Each market
> reports its type in `sports.sports_market_type` when present.
>
> ```python theme={null}
> market_types = await client.get_sports_market_types()
>
> # market_types.market_types: tuple[str, ...] | None
> ```
>
> > [accordion] Output: string\[]
> >
> > ```json Example theme={null}
> > {
> >   "market_types": ["moneyline", "spreads", "totals"]
> > }
> > ```
>
> Filter markets by type:
>
> ```python theme={null}
> pages = client.list_markets(
>     sports_market_types=["spreads"],
>     closed=False,
>     page_size=20,
> )
>
> async for page in pages:
>     ...  # page.items: tuple[Market, ...]
> ```

> [tab] API
>
> List supported sports market types. When present, a market reports its type in
> `sportsMarketType`:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/sports/market-types"
> ```
>
> > [accordion] Output: string\[]
> >
> > ```json Example theme={null}
> > {
> >   "marketTypes": ["moneyline", "spreads", "totals"]
> > }
> > ```
>
> Filter markets by type:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/markets/keyset?sports_market_types=spreads&closed=false&limit=20"
> ```

### List Events for a Game

A sports game's markets can be split across a main event and companion events. Depending on the game, companion events may cover player props, half-time and second-half results, exact score, or additional lines grouped under a more-markets event. Their slugs extend the main event's slug with a suffix such as `-player-props`, `-halftime-result`, or `-more-markets`.

Append a known suffix when you need one companion event. To discover current companion events, use the listing workflow instead of guessing each suffix.

> [tab] TypeScript
>
> Call `fetchEvent()` on a `PublicClient` or `SecureClient`. To fetch only the
> more-markets event, append `-more-markets` to the main event's slug.
>
> ```ts theme={null}
> const mainSlug = "mls-chi-vwh-2026-07-16";
>
> const moreMarkets = await client.fetchEvent({
>   slug: `${mainSlug}-more-markets`,
> });
> ```
>
> To list the game's current events, fetch the main event and read `sports.gameId`, then
> pass it to `listEvents()`. Not every event has a game ID, so check it before filtering.
>
> ```ts theme={null}
> const mainSlug = "mls-chi-vwh-2026-07-16";
> const game = await client.fetchEvent({ slug: mainSlug });
> const gameId = game.sports.gameId;
>
> if (gameId == null) {
>   throw new Error("Event does not have a game ID");
> }
>
> const pages = client.listEvents({ gameIds: [gameId], pageSize: 20 });
>
> for await (const page of pages) {
>   // page.items: Event[]
> }
> ```
>
> > [accordion] Output: Event Page
> >
> > ```json Example theme={null}
> > {
> >   "items": [
> >     {
> >       "id": "662915",
> >       "slug": "mls-chi-vwh-2026-07-16",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC"
> >     },
> >     {
> >       "id": "662970",
> >       "slug": "mls-chi-vwh-2026-07-16-halftime-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Halftime Result"
> >     },
> >     {
> >       "id": "662972",
> >       "slug": "mls-chi-vwh-2026-07-16-second-half-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Second Half Result"
> >     },
> >     {
> >       "id": "662974",
> >       "slug": "mls-chi-vwh-2026-07-16-exact-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Exact Score"
> >     },
> >     {
> >       "id": "662976",
> >       "slug": "mls-chi-vwh-2026-07-16-first-to-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - First Team to Score"
> >     },
> >     {
> >       "id": "663131",
> >       "slug": "mls-chi-vwh-2026-07-16-more-markets",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - More Markets"
> >     }
> >   ],
> >   "hasMore": false
> > }
> > ```
>
> When present, `market.sports.sportsMarketType` identifies lines in the more-markets
> event such as `first_half_totals`, `both_teams_to_score`, and `soccer_team_totals`.

> [tab] Python
>
> Call `get_event()` on an `AsyncPublicClient` or `AsyncSecureClient`. To fetch only the
> more-markets event, append `-more-markets` to the main event's slug. The synchronous
> `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> main_slug = "mls-chi-vwh-2026-07-16"
>
> more_markets = await client.get_event(slug=f"{main_slug}-more-markets")
> ```
>
> To list the game's current events, fetch the main event and read `sports.game_id`, then
> pass it to `list_events()`. Not every event has a game ID, so check it before filtering.
>
> ```python theme={null}
> main_slug = "mls-chi-vwh-2026-07-16"
> game = await client.get_event(slug=main_slug)
> game_id = game.sports.game_id
>
> if game_id is None:
>     raise ValueError("Event does not have a game ID")
>
> pages = client.list_events(game_ids=[game_id], page_size=20)
>
> async for page in pages:
>     ...  # page.items: tuple[Event, ...]
> ```
>
> > [accordion] Output: Event Page
> >
> > ```json Example theme={null}
> > {
> >   "items": [
> >     {
> >       "id": "662915",
> >       "slug": "mls-chi-vwh-2026-07-16",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC"
> >     },
> >     {
> >       "id": "662970",
> >       "slug": "mls-chi-vwh-2026-07-16-halftime-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Halftime Result"
> >     },
> >     {
> >       "id": "662972",
> >       "slug": "mls-chi-vwh-2026-07-16-second-half-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Second Half Result"
> >     },
> >     {
> >       "id": "662974",
> >       "slug": "mls-chi-vwh-2026-07-16-exact-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Exact Score"
> >     },
> >     {
> >       "id": "662976",
> >       "slug": "mls-chi-vwh-2026-07-16-first-to-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - First Team to Score"
> >     },
> >     {
> >       "id": "663131",
> >       "slug": "mls-chi-vwh-2026-07-16-more-markets",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - More Markets"
> >     }
> >   ],
> >   "has_more": false
> > }
> > ```
>
> When present, `market.sports.sports_market_type` identifies lines in the more-markets
> event such as `first_half_totals`, `both_teams_to_score`, and `soccer_team_totals`.

> [tab] API
>
> To fetch only the more-markets event, append `-more-markets` to the main event's slug:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/slug/mls-chi-vwh-2026-07-16-more-markets"
> ```
>
> To list the game's current events, fetch the main event and read its `gameId`:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/slug/mls-chi-vwh-2026-07-16"
> ```
>
> Pass the ID as `game_id`:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/keyset?game_id=90104306&limit=20"
> ```
>
> > [accordion] Output: Events Page
> >
> > ```json Example theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "662915",
> >       "slug": "mls-chi-vwh-2026-07-16",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC",
> >       "gameId": 90104306
> >     },
> >     {
> >       "id": "662970",
> >       "slug": "mls-chi-vwh-2026-07-16-halftime-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Halftime Result",
> >       "gameId": 90104306
> >     },
> >     {
> >       "id": "662972",
> >       "slug": "mls-chi-vwh-2026-07-16-second-half-result",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Second Half Result",
> >       "gameId": 90104306
> >     },
> >     {
> >       "id": "662974",
> >       "slug": "mls-chi-vwh-2026-07-16-exact-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - Exact Score",
> >       "gameId": 90104306
> >     },
> >     {
> >       "id": "662976",
> >       "slug": "mls-chi-vwh-2026-07-16-first-to-score",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - First Team to Score",
> >       "gameId": 90104306
> >     },
> >     {
> >       "id": "663131",
> >       "slug": "mls-chi-vwh-2026-07-16-more-markets",
> >       "title": "Chicago Fire FC vs. Vancouver Whitecaps FC - More Markets",
> >       "gameId": 90104306
> >     }
> >   ]
> > }
> > ```
>
> If the response includes `next_cursor`, pass it as `after_cursor` in the next request.
> When present, `market.sportsMarketType` identifies lines in the more-markets event such
> as `first_half_totals`, `both_teams_to_score`, and `soccer_team_totals`.

### Identify Home and Away Teams

Sports event responses identify which team is designated home and which is
designated away. Use this value when aligning Polymarket data with an external
sports feed.

> [tab] TypeScript
>
> Use `PublicClient.fetchEvent()` or `SecureClient.fetchEvent()` to identify the teams.
>
> ```ts theme={null}
> import { TeamOrdering } from "@polymarket/client";
>
> const event = await client.fetchEvent({
>   slug: "fl1-psg-ren-2026-08-23",
> });
> const homeTeam = event.sports.teams.find(
>   (team) => team.ordering === TeamOrdering.Home,
> );
> const awayTeam = event.sports.teams.find(
>   (team) => team.ordering === TeamOrdering.Away,
> );
> ```
>
> > [accordion] Output: Team
> >
> > ```json theme={null}
> > {
> >   "id": 114315,
> >   "name": "Paris Saint-Germain FC",
> >   "league": "fl1",
> >   "abbreviation": "psg",
> >   "ordering": "home"
> > }
> > ```
>
> Each `Team.ordering` value is `TeamOrdering.Home`, `TeamOrdering.Away`, or `null`.

> [tab] Python
>
> Use `AsyncPublicClient.get_event()` or `AsyncSecureClient.get_event()` to identify the teams.
>
> ```python theme={null}
> from polymarket import TeamOrdering
>
>
> event = await client.get_event(slug="fl1-psg-ren-2026-08-23")
> home_team = next(
>     (team for team in event.sports.teams if team.ordering is TeamOrdering.HOME),
>     None,
> )
> away_team = next(
>     (team for team in event.sports.teams if team.ordering is TeamOrdering.AWAY),
>     None,
> )
> ```
>
> > [accordion] Output: Team
> >
> > ```json theme={null}
> > {
> >   "id": 114315,
> >   "name": "Paris Saint-Germain FC",
> >   "league": "fl1",
> >   "abbreviation": "psg",
> >   "ordering": "home"
> > }
> > ```
>
> Each `Team.ordering` value is `TeamOrdering.HOME`, `TeamOrdering.AWAY`, or `None`.

> [tab] API
>
> Fetch the event by slug to identify its home and away teams.
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/events/slug/fl1-psg-ren-2026-08-23"
> ```
>
> > [accordion] Output: Event
> >
> > ```jsonc theme={null}
> > {
> >   "slug": "fl1-psg-ren-2026-08-23",
> >   "title": "Paris Saint-Germain FC vs. Stade Rennais FC 1901",
> >   // …
> >   "teams": [
> >     {
> >       "id": 114315,
> >       "name": "Paris Saint-Germain FC",
> >       // …
> >       "ordering": "home",
> >     },
> >     {
> >       "id": 114317,
> >       "name": "Stade Rennais FC 1901",
> >       // …
> >       "ordering": "away",
> >     },
> >   ],
> > }
> > ```
>
> Read `ordering` from each entry in the event's top-level `teams` field. Its
> value is `"home"`, `"away"`, or `null`.

> [!WARNING]
>
> Home and away assignments can change after markets are created, especially
> when games are rescheduled or moved. If you plan to submit quotes in Combos,
> check [Common Footguns](https://docs.polymarket.com/trading/combos/market-makers.md#common-footguns).

### List Teams

> [tab] TypeScript
>
> Call `listTeams()` on a `PublicClient` or `SecureClient` to page through teams.
>
> ```ts theme={null}
> const pages = client.listTeams({ league: ["nba"], pageSize: 20 });
>
> for await (const page of pages) {
>   // page.items: Team[]
> }
> ```
>
> > [accordion] Output: Team\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": 114168,
> >     "name": "Candace's Rising Stars",
> >     "league": "nba",
> >     "abbreviation": "crs"
> >   },
> >   {
> >     "id": 114166,
> >     "name": "Chuck's Global Stars",
> >     "league": "nba",
> >     "abbreviation": "cgs"
> >   },
> >   "..."
> > ]
> > ```

> [tab] Python
>
> Call `list_teams()` on an `AsyncPublicClient` or `AsyncSecureClient` to page
> through teams. The synchronous `PublicClient` and `SecureClient` provide the
> same method.
>
> ```python theme={null}
> pages = client.list_teams(league="nba", page_size=20)
>
> async for page in pages:
>     ...  # page.items: tuple[Team, ...]
> ```
>
> > [accordion] Output: Team\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": 114168,
> >     "name": "Candace's Rising Stars",
> >     "league": "nba",
> >     "abbreviation": "crs"
> >   },
> >   {
> >     "id": 114166,
> >     "name": "Chuck's Global Stars",
> >     "league": "nba",
> >     "abbreviation": "cgs"
> >   },
> >   "..."
> > ]
> > ```

> [tab] API
>
> List teams in a league:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/teams?league=nba&limit=20"
> ```
>
> > [accordion] Output: Team\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": 114168,
> >     "name": "Candace's Rising Stars",
> >     "league": "nba",
> >     "abbreviation": "crs"
> >   },
> >   "..."
> > ]
> > ```

## Search

Search returns matching events, tags, and profiles for a free-text query in one call. Use it for a search bar or a "jump to market" input.

> [tab] TypeScript
>
> Call `search()` on a `PublicClient` or `SecureClient` to search Polymarket.
>
> ```ts theme={null}
> const pages = client.search({ q: "aliens", pageSize: 10 });
>
> for await (const page of pages) {
>   // page.items.events: Event[]
>   // page.items.tags: SearchTag[]
>   // page.items.profiles: Profile[]
> }
> ```
>
> > [accordion] Output: SearchResults
> >
> > ```ts SearchResults Type theme={null}
> > type Event = {
> >   id: string;
> >   slug?: string | null;
> >   title?: string | null;
> > };
> >
> > type SearchTag = {
> >   id: string;
> >   label?: string | null;
> >   slug?: string | null;
> >   eventCount?: number | null;
> > };
> >
> > type Profile = {
> >   pseudonym?: string | null;
> >   wallet?: string | null;
> > };
> >
> > type SearchResults = {
> >   events: Event[];
> >   tags: SearchTag[];
> >   profiles: Profile[];
> > };
> > ```
> >
> > ```json SearchResults Example theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "90177",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >       "title": "Will the US confirm that aliens exist by...?"
> >     },
> >     "..."
> >   ],
> >   "tags": [],
> >   "profiles": []
> > }
> > ```

> [tab] Python
>
> Call `search()` on an `AsyncPublicClient` or `AsyncSecureClient` to search
> Polymarket. The synchronous `PublicClient` and `SecureClient` provide the
> same method.
>
> ```python theme={null}
> pages = client.search(q="aliens", page_size=10)
>
> async for page in pages:
>     for search_results in page.items:
>         # search_results.events: tuple[Event, ...]
>         # search_results.tags: tuple[SearchTag, ...]
>         # search_results.profiles: tuple[Profile, ...]
>         ...
> ```
>
> > [accordion] Output: SearchResults
> >
> > ```python SearchResults Type theme={null}
> > class Event:
> >     id: str
> >     slug: str | None
> >     title: str | None
> >
> > class SearchTag:
> >     id: str
> >     label: str | None
> >     slug: str | None
> >     event_count: int | None
> >
> > class Profile:
> >     pseudonym: str | None
> >     wallet: str | None
> >
> > class SearchResults:
> >     events: tuple[Event, ...]
> >     tags: tuple[SearchTag, ...]
> >     profiles: tuple[Profile, ...]
> > ```
> >
> > ```json SearchResults Example theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "90177",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >       "title": "Will the US confirm that aliens exist by...?"
> >     },
> >     "..."
> >   ],
> >   "tags": [],
> >   "profiles": []
> > }
> > ```

> [tab] API
>
> Search Polymarket:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/public-search?q=aliens"
> ```
>
> > [accordion] Output: Search
> >
> > ```json Example theme={null}
> > {
> >   "events": [
> >     {
> >       "id": "90177",
> >       "slug": "will-the-us-confirm-that-aliens-exist-before-2027",
> >       "title": "Will the US confirm that aliens exist by...?"
> >     },
> >     "..."
> >   ],
> >   "tags": [],
> >   "profiles": [],
> >   "pagination": {
> >     "hasMore": true,
> >     "totalResults": 28
> >   }
> > }
> > ```

## Tags

Tags group events and markets by categories, leagues, people, and themes. Each
tag can link to multiple ranked related tags, forming a directed graph rather
than a strict tree. Use these relationships to expand discovery from one topic
to adjacent topics.

### List Tags

Browse the available tags, for example to build a category filter.

> [tab] TypeScript
>
> Call `listTags()` on a `PublicClient` or `SecureClient` to page through tags.
>
> ```ts theme={null}
> const pages = client.listTags({ pageSize: 20 });
>
> for await (const page of pages) {
>   // page.items: Tag[]
> }
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": "101867",
> >     "slug": "product-marekt-fit",
> >     "label": "product marekt fit"
> >   },
> >   { "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" },
> >   "..."
> > ]
> > ```

> [tab] Python
>
> Call `list_tags()` on an `AsyncPublicClient` or `AsyncSecureClient` to page
> through tags. The synchronous `PublicClient` and `SecureClient` provide the
> same method.
>
> ```python theme={null}
> pages = client.list_tags(page_size=20)
>
> async for page in pages:
>     ...  # page.items: tuple[Tag, ...]
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": "101867",
> >     "slug": "product-marekt-fit",
> >     "label": "product marekt fit"
> >   },
> >   { "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" },
> >   "..."
> > ]
> > ```

> [tab] API
>
> List tags:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/tags?limit=20"
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [
> >   {
> >     "id": "101867",
> >     "slug": "product-marekt-fit",
> >     "label": "product marekt fit"
> >   },
> >   { "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" },
> >   "..."
> > ]
> > ```

### Fetch a Tag

Fetch a tag by slug to resolve its numeric ID. You'll need that ID for the `tagId`/`tagIds` filters used earlier in Events and Markets.

> [tab] TypeScript
>
> Call `fetchTag()` on a `PublicClient` or `SecureClient` to fetch a tag by slug.
>
> ```ts theme={null}
> const nba = await client.fetchTag({ slug: "nba" });
>
> // nba: Tag
> ```
>
> > [accordion] Output: Tag
> >
> > ```json Example theme={null}
> > { "id": "745", "slug": "nba", "label": "NBA" }
> > ```

> [tab] Python
>
> Call `get_tag()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch a
> tag by slug. The synchronous `PublicClient` and `SecureClient` provide the
> same method.
>
> ```python theme={null}
> nba = await client.get_tag(slug="nba")
>
> # nba: Tag
> ```
>
> > [accordion] Output: Tag
> >
> > ```json Example theme={null}
> > { "id": "745", "slug": "nba", "label": "NBA" }
> > ```

> [tab] API
>
> Fetch a tag by slug:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/tags/slug/nba"
> ```
>
> > [accordion] Output: Tag
> >
> > ```json Example theme={null}
> > { "id": "745", "slug": "nba", "label": "NBA" }
> > ```

### Fetch Tag Relationships

Get the relationship records that link a tag to related tags, useful for building "you might also like" surfaces. Each record is a lightweight pointer (a rank and the two numeric tag IDs), not a full tag object.

> [tab] TypeScript
>
> Call `fetchRelatedTags()` on a `PublicClient` or `SecureClient` to fetch a tag's
> relationship records.
>
> ```ts theme={null}
> const relatedTags = await client.fetchRelatedTags({ slug: "nba" });
>
> // relatedTags: RelatedTag[]
> ```
>
> > [accordion] Output: RelatedTag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "58212", "tagId": 745, "relatedTagId": 1512, "rank": 1 }]
> > ```

> [tab] Python
>
> Call `get_related_tags()` on an `AsyncPublicClient` or `AsyncSecureClient`
> to fetch a tag's relationship records. The synchronous `PublicClient` and
> `SecureClient` provide the same method.
>
> ```python theme={null}
> related_tags = await client.get_related_tags(slug="nba")
>
> # related_tags: tuple[RelatedTag, ...]
> ```
>
> > [accordion] Output: RelatedTag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "58212", "tag_id": 745, "related_tag_id": 1512, "rank": 1 }]
> > ```

> [tab] API
>
> Fetch a tag's relationship records:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/tags/slug/nba/related-tags"
> ```
>
> > [accordion] Output: RelatedTag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "58212", "tagID": 745, "relatedTagID": 1512, "rank": 1 }]
> > ```

### Fetch Related Tags

Get the full `Tag` objects for a tag's related tags in one call, skipping the extra round trip to fetch each related tag by ID.

> [tab] TypeScript
>
> Call `fetchRelatedTagResources()` on a `PublicClient` or `SecureClient` to fetch the
> related tag objects.
>
> ```ts theme={null}
> const relatedTagObjects = await client.fetchRelatedTagResources({
>   slug: "nba",
>   status: "active",
> });
>
> // relatedTagObjects: Tag[]
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" }]
> > ```

> [tab] Python
>
> Call `get_related_tag_resources()` on an `AsyncPublicClient` or
> `AsyncSecureClient` to fetch the related tag objects. The synchronous
> `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> related_tag_objects = await client.get_related_tag_resources(
>     slug="nba",
>     status="active",
> )
>
> # related_tag_objects: tuple[Tag, ...]
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" }]
> > ```

> [tab] API
>
> Fetch the related tag objects:
>
> ```bash theme={null}
> curl "https://gamma-api.polymarket.com/tags/slug/nba/related-tags/tags"
> ```
>
> > [accordion] Output: Tag\[]
> >
> > ```json Example theme={null}
> > [{ "id": "1512", "slug": "caitlin-clark", "label": "caitlin clark" }]
> > ```

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.

> ## Documentation Index
>
> Fetch the complete documentation index at: https://docs.polymarket.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Prices and Order Books

> Learn how prices and order books represent trading activity on Polymarket.

Each Polymarket outcome has an outcome token traded on the CLOB. Its price
reflects what traders are willing to pay, while its order book shows the
resting bids and asks.

The examples below assume you already have a market object from which to read
the outcome IDs. To find or fetch one, see
[**Discover Markets**](https://docs.polymarket.com/market-data/discover-markets.md).

> [tab] TypeScript
>
> The unified SDK uses `assetId` for an outcome's trading identifier: a token
> ID for a CTF market or a position ID for a Polymarket Protocol V2 market.
> Use the identifier exposed for that outcome.
>
> Select both outcome IDs from the market:
>
> ```ts theme={null}
> const yesAssetId =
>   market.version === "v2"
>     ? market.outcomes.yes.positionId
>     : market.outcomes.yes.tokenId;
> if (yesAssetId === null) {
>   throw new Error("Market outcome ID not found.");
> }
> const noAssetId =
>   market.version === "v2"
>     ? market.outcomes.no.positionId
>     : market.outcomes.no.tokenId;
> if (noAssetId === null) {
>   throw new Error("Market outcome ID not found.");
> }
> ```

> [tab] Python
>
> The unified SDK uses `asset_id` for an outcome's trading identifier: a token
> ID for a CTF market or a position ID for a Polymarket Protocol V2 market.
> Use the identifier exposed for that outcome.
>
> Select both outcome IDs from the market:
>
> ```python theme={null}
> yes_asset_id = (
>     market.outcomes.yes.position_id
>     if market.version == "v2"
>     else market.outcomes.yes.token_id
> )
> if yes_asset_id is None:
>     raise ValueError("Market outcome ID not found.")
> no_asset_id = (
>     market.outcomes.no.position_id
>     if market.version == "v2"
>     else market.outcomes.no.token_id
> )
> if no_asset_id is None:
>     raise ValueError("Market outcome ID not found.")
> ```

> [tab] API
>
> Gamma returns `positionIds` as a JSON array. Use `version` to select it for
> Polymarket Protocol V2 markets or parse the JSON-encoded `clobTokenIds` for
> CTF markets:
>
> ```json theme={null}
> {
>   "version": "v2",
>   "positionIds": [
>     "651150819117105875331414918119047680898421632356043490229292782433651916800",
>     "651150819117105875331414918119047680898421632356043490229292782433651916801"
>   ]
> }
> ```
>
> Select the outcome you want to read:
>
> ```bash theme={null}
> TOKEN_ID="<yes_asset_id>"
> ```

## Order Book

Retrieve the resting bids and asks for one outcome. Bids are ordered by
ascending price and asks by descending price, so the best bid and ask are the
last entries in their respective arrays. Each response also includes a `hash`
for the order-book state. Compare it with the previous response's hash to
determine whether the book changed between reads.

### Fetch an Order Book

> [tab] TypeScript
>
> Call `fetchOrderBook()` on a `PublicClient` or `SecureClient` to fetch an outcome's
> order book.
>
> ```ts theme={null}
> const book = await client.fetchOrderBook({ assetId: yesAssetId });
>
> // book: OrderBook
> ```
>
> The returned `OrderBook` describes its price levels and the market details
> needed to interpret them:
>
> ```ts OrderBook Type theme={null}
> type OrderBookLevel = {
>   price: DecimalString;
>   size: DecimalString;
> };
>
> type OrderBook = {
>   conditionId: ConditionId;
>   assetId: ClobAssetId;
>   timestamp?: EpochMilliseconds | null;
>   bids: OrderBookLevel[];
>   asks: OrderBookLevel[];
>   minOrderSize: DecimalString;
>   tickSize: DecimalString;
>   negRisk: boolean;
>   lastTradePrice?: DecimalString | null;
>   hash: OrderBookHash;
> };
> ```
>
> ```json OrderBook Example theme={null}
> {
>   "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>   "assetId": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>   "timestamp": 1782753404902,
>   "bids": [
>     { "price": "0.01", "size": "2116131.59" },
>     { "price": "0.02", "size": "139963.89" },
>     { "price": "0.03", "size": "208169.44" },
>     "..."
>   ],
>   "asks": [
>     { "price": "0.99", "size": "93442.27" },
>     { "price": "0.98", "size": "13229.55" },
>     { "price": "0.97", "size": "4338.7" },
>     "..."
>   ],
>   "minOrderSize": "5",
>   "tickSize": "0.01",
>   "negRisk": false,
>   "lastTradePrice": "0.090",
>   "hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
> }
> ```

> [tab] Python
>
> Call `get_order_book()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch an outcome's order book. The synchronous `PublicClient` and
> `SecureClient` provide the same method.
>
> ```python theme={null}
> book = await client.get_order_book(asset_id=yes_asset_id)
>
> # book: OrderBook
> ```
>
> The returned `OrderBook` describes its price levels and the market details
> needed to interpret them:
>
> ```python OrderBook Type theme={null}
> class OrderBookLevel:
>     price: Decimal
>     size: Decimal
>
> class OrderBook:
>     condition_id: ConditionId
>     asset_id: ClobAssetId
>     timestamp: datetime | None
>     bids: tuple[OrderBookLevel, ...]
>     asks: tuple[OrderBookLevel, ...]
>     min_order_size: Decimal
>     tick_size: Decimal
>     neg_risk: bool
>     last_trade_price: Decimal | None
>     hash: str
> ```
>
> ```json OrderBook Example theme={null}
> {
>   "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>   "asset_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>   "timestamp": "2026-06-29T17:16:44.902000+00:00",
>   "bids": [
>     { "price": "0.01", "size": "2116131.59" },
>     { "price": "0.02", "size": "139963.89" },
>     { "price": "0.03", "size": "208169.44" },
>     "..."
>   ],
>   "asks": [
>     { "price": "0.99", "size": "93442.27" },
>     { "price": "0.98", "size": "13229.55" },
>     { "price": "0.97", "size": "4338.7" },
>     "..."
>   ],
>   "min_order_size": "5",
>   "tick_size": "0.01",
>   "neg_risk": false,
>   "last_trade_price": "0.090",
>   "hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
> }
> ```

> [tab] API
>
> Fetch an outcome's order book:
>
> ```bash theme={null}
> curl "https://clob.polymarket.com/book?token_id=$TOKEN_ID"
> ```
>
> Alongside its price levels, the response includes the trading constraints
> needed to validate an order:
>
> ```json theme={null}
> {
>   "market": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>   "asset_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>   "timestamp": "1782753357257",
>   "hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
>   "bids": [
>     { "price": "0.01", "size": "2151131.59" },
>     { "price": "0.02", "size": "139963.89" },
>     { "price": "0.03", "size": "208169.44" },
>     "..."
>   ],
>   "asks": [
>     { "price": "0.99", "size": "218442.27" },
>     { "price": "0.98", "size": "13229.55" },
>     { "price": "0.97", "size": "4338.7" },
>     "..."
>   ],
>   "min_order_size": "5",
>   "tick_size": "0.01",
>   "neg_risk": false,
>   "last_trade_price": "0.090"
> }
> ```

### Fetch Multiple Order Books

Batch order-book reads return the resting bids and asks for several outcomes in
one request.

> [!NOTE]
>
> Maximum 500 items per request.

> [tab] TypeScript
>
> Call `fetchOrderBooks()` on a `PublicClient` or `SecureClient` to fetch several order
> books in one request.
>
> ```ts theme={null}
> const books = await client.fetchOrderBooks([
>   { assetId: yesAssetId },
>   { assetId: noAssetId },
> ]);
>
> // books: OrderBook[]
> ```
>
> Each item uses the `OrderBook` shape described above:
>
> ```json theme={null}
> [
>   {
>     "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "bids": [
>       { "price": "0.01", "size": "2116131.59" },
>       { "price": "0.02", "size": "139963.89" },
>       { "price": "0.03", "size": "208169.44" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "93442.27" },
>       { "price": "0.98", "size": "13229.55" },
>       { "price": "0.97", "size": "4338.7" },
>       "..."
>     ]
>   },
>   {
>     "conditionId": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "bids": [
>       { "price": "0.01", "size": "93442.27" },
>       { "price": "0.02", "size": "13229.55" },
>       { "price": "0.03", "size": "4338.7" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "2116131.59" },
>       { "price": "0.98", "size": "139963.89" },
>       { "price": "0.97", "size": "208169.44" },
>       "..."
>     ]
>   }
> ]
> ```

> [tab] Python
>
> Call `get_order_books()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch several order books in one request. The synchronous `PublicClient`
> and `SecureClient` provide the same method.
>
> ```python theme={null}
> books = await client.get_order_books(asset_ids=[yes_asset_id, no_asset_id])
>
> # books: tuple[OrderBook, ...]
> ```
>
> Each item uses the `OrderBook` shape described above:
>
> ```json theme={null}
> [
>   {
>     "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "bids": [
>       { "price": "0.01", "size": "2116131.59" },
>       { "price": "0.02", "size": "139963.89" },
>       { "price": "0.03", "size": "208169.44" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "93442.27" },
>       { "price": "0.98", "size": "13229.55" },
>       { "price": "0.97", "size": "4338.7" },
>       "..."
>     ]
>   },
>   {
>     "condition_id": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "bids": [
>       { "price": "0.01", "size": "93442.27" },
>       { "price": "0.02", "size": "13229.55" },
>       { "price": "0.03", "size": "4338.7" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "2116131.59" },
>       { "price": "0.98", "size": "139963.89" },
>       { "price": "0.97", "size": "208169.44" },
>       "..."
>     ]
>   }
> ]
> ```

> [tab] API
>
> Fetch several order books in one request:
>
> ```bash theme={null}
> curl -X POST "https://clob.polymarket.com/books" \
>   -H "Content-Type: application/json" \
>   --data '[{"token_id":"<yes_asset_id>"},{"token_id":"<no_asset_id>"}]'
> ```
>
> The response contains one order book for each requested outcome identifier:
>
> ```json theme={null}
> [
>   {
>     "market": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "asset_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>     "timestamp": "1782753357257",
>     "hash": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
>     "bids": [
>       { "price": "0.01", "size": "2151131.59" },
>       { "price": "0.02", "size": "139963.89" },
>       { "price": "0.03", "size": "208169.44" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "218442.27" },
>       { "price": "0.98", "size": "13229.55" },
>       { "price": "0.97", "size": "4338.7" },
>       "..."
>     ],
>     "min_order_size": "5",
>     "tick_size": "0.01",
>     "neg_risk": false,
>     "last_trade_price": "0.090"
>   },
>   {
>     "market": "0x747dc809fb79e1b05be09c42d6179459a58de2ef3e40f02484a4e1260f741f75",
>     "asset_id": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
>     "timestamp": "1782753357257",
>     "hash": "f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5",
>     "bids": [
>       { "price": "0.01", "size": "218442.27" },
>       { "price": "0.02", "size": "13229.55" },
>       { "price": "0.03", "size": "4338.7" },
>       "..."
>     ],
>     "asks": [
>       { "price": "0.99", "size": "2151131.59" },
>       { "price": "0.98", "size": "139963.89" },
>       { "price": "0.97", "size": "208169.44" },
>       "..."
>     ],
>     "min_order_size": "5",
>     "tick_size": "0.01",
>     "neg_risk": true,
>     "last_trade_price": "0.910"
>   }
> ]
> ```

## Best Market Price

Read the best available execution price for an outcome and side. `BUY` returns
the lowest ask, which is the price you would pay to buy. `SELL` returns the
highest bid, which is the price you would receive when selling.

### Fetch a Price

> [tab] TypeScript
>
> Call `fetchPrice()` on a `PublicClient` or `SecureClient` to fetch the best price for
> one side. For a `BUY`, the method returns the lowest ask.
>
> ```ts theme={null}
> import { OrderSide } from "@polymarket/client";
>
> const price = await client.fetchPrice({
>   assetId: yesAssetId,
>   side: OrderSide.BUY,
> });
>
> // price: DecimalString
> ```
>
> The method returns the price as a decimal string:
>
> ```json theme={null}
> "0.08"
> ```

> [tab] Python
>
> Call `get_price()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch
> the best price for one side. For a `BUY`, the method returns the lowest ask.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> price = await client.get_price(asset_id=yes_asset_id, side="BUY")
>
> # price: Decimal
> ```
>
> The method returns the price as a `Decimal`:
>
> ```python theme={null}
> Decimal("0.08")
> ```

> [tab] API
>
> Fetch the lowest ask available to a buyer:
>
> ```bash theme={null}
> curl "https://clob.polymarket.com/price?token_id=$TOKEN_ID&side=BUY"
> ```
>
> The response contains the price as a decimal string:
>
> ```json theme={null}
> { "price": "0.08" }
> ```

### Fetch Multiple Prices

Batch price reads return the best market price for several outcome-and-side pairs
in one request. Use them when the same view or calculation needs more than one
outcome.

> [!NOTE]
>
> Maximum 500 items per request.

> [tab] TypeScript
>
> Call `fetchPrices()` on a `PublicClient` or `SecureClient` to fetch several prices in
> one request.
>
> ```ts theme={null}
> import { OrderSide } from "@polymarket/client";
>
> const prices = await client.fetchPrices([
>   { assetId: yesAssetId, side: OrderSide.BUY },
>   { assetId: noAssetId, side: OrderSide.BUY },
> ]);
>
> // prices: Prices (map of assetId -> side -> price)
> ```
>
> `Prices` maps each outcome identifier to the requested side and price:
>
> ```ts Prices Type theme={null}
> type Prices = Record<ClobAssetId, Partial<Record<OrderSide, DecimalString>>>;
> ```
>
> ```json Prices Example theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": {
>     "BUY": "0.08"
>   },
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": {
>     "BUY": "0.91"
>   }
> }
> ```

> [tab] Python
>
> Call `get_prices()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch several prices in one request. The synchronous `PublicClient` and
> `SecureClient` provide the same method.
>
> ```python theme={null}
> from polymarket import PriceRequest
>
> prices = await client.get_prices(
>     requests=[
>         PriceRequest(asset_id=yes_asset_id, side="BUY"),
>         PriceRequest(asset_id=no_asset_id, side="BUY"),
>     ],
> )
>
> # prices: dict[ClobAssetId, dict[OrderSide, Decimal]]
> ```
>
> The result maps each outcome identifier to the requested side and price:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": {
>     "BUY": "0.08"
>   },
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": {
>     "BUY": "0.91"
>   }
> }
> ```

> [tab] API
>
> Fetch several prices in one request:
>
> ```bash theme={null}
> curl -X POST "https://clob.polymarket.com/prices" \
>   -H "Content-Type: application/json" \
>   --data '[{"token_id":"<yes_asset_id>","side":"BUY"},{"token_id":"<no_asset_id>","side":"BUY"}]'
> ```
>
> The response maps each outcome identifier to the requested side and price:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": {
>     "BUY": 0.08
>   },
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": {
>     "BUY": 0.91
>   }
> }
> ```

## Midpoint Price

The midpoint is the average of the best bid and best ask. It provides a reference
price between the two sides of the order book.

### Fetch a Midpoint

> [tab] TypeScript
>
> Call `fetchMidpoint()` on a `PublicClient` or `SecureClient` to fetch the midpoint.
>
> ```ts theme={null}
> const midpoint = await client.fetchMidpoint({ assetId: yesAssetId });
>
> // midpoint: DecimalString
> ```
>
> The method returns the midpoint as a decimal string:
>
> ```json theme={null}
> "0.085"
> ```

> [tab] Python
>
> Call `get_midpoint()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch the midpoint.
> The synchronous `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> midpoint = await client.get_midpoint(asset_id=yes_asset_id)
>
> # midpoint: Decimal
> ```
>
> The method returns the midpoint as a `Decimal`:
>
> ```python theme={null}
> Decimal("0.085")
> ```

> [tab] API
>
> Fetch the midpoint:
>
> ```bash theme={null}
> curl "https://clob.polymarket.com/midpoint?token_id=$TOKEN_ID"
> ```
>
> The response contains the midpoint as a decimal string:
>
> ```json theme={null}
> { "mid": "0.085" }
> ```

### Fetch Multiple Midpoints

Fetch midpoint prices for several outcomes in one request.

> [!NOTE]
>
> Maximum 500 items per request.

> [tab] TypeScript
>
> Call `fetchMidpoints()` on a `PublicClient` or `SecureClient` to fetch several
> midpoints.
>
> ```ts theme={null}
> const midpoints = await client.fetchMidpoints([
>   { assetId: yesAssetId },
>   { assetId: noAssetId },
> ]);
>
> // midpoints: Midpoints
> ```
>
> `Midpoints` maps each outcome identifier to its midpoint:
>
> ```ts Midpoints Type theme={null}
> type Midpoints = Record<ClobAssetId, DecimalString>;
> ```
>
> ```json Midpoints Example theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.085",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.915"
> }
> ```

> [tab] Python
>
> Call `get_midpoints()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch several midpoints. The synchronous `PublicClient` and `SecureClient`
> provide the same method.
>
> ```python theme={null}
> midpoints = await client.get_midpoints(asset_ids=[yes_asset_id, no_asset_id])
>
> # midpoints: dict[ClobAssetId, Decimal]
> ```
>
> The result maps each outcome identifier to its midpoint:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.085",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.915"
> }
> ```

> [tab] API
>
> Fetch several midpoints in one request:
>
> ```bash theme={null}
> curl -X POST "https://clob.polymarket.com/midpoints" \
>   -H "Content-Type: application/json" \
>   --data '[{"token_id":"<yes_asset_id>"},{"token_id":"<no_asset_id>"}]'
> ```
>
> The response maps each outcome identifier to its midpoint:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.085",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.915"
> }
> ```

## Spread

The spread is the difference between the best ask and best bid. A narrower
spread indicates that the two sides of the order book are closer together.

### Fetch a Spread

> [tab] TypeScript
>
> Call `fetchSpread()` on a `PublicClient` or `SecureClient` to fetch the spread.
>
> ```ts theme={null}
> const spread = await client.fetchSpread({ assetId: yesAssetId });
>
> // spread: DecimalString
> ```
>
> The method returns the spread as a decimal string:
>
> ```json theme={null}
> "0.01"
> ```

> [tab] Python
>
> Call `get_spread()` on an `AsyncPublicClient` or `AsyncSecureClient` to fetch
> the spread. The synchronous `PublicClient` and `SecureClient` provide the
> same method.
>
> ```python theme={null}
> spread = await client.get_spread(asset_id=yes_asset_id)
>
> # spread: Decimal
> ```
>
> The method returns the spread as a `Decimal`:
>
> ```python theme={null}
> Decimal("0.01")
> ```

> [tab] API
>
> Fetch the spread:
>
> ```bash theme={null}
> curl "https://clob.polymarket.com/spread?token_id=$TOKEN_ID"
> ```
>
> The response contains the spread as a decimal string:
>
> ```json theme={null}
> { "spread": "0.01" }
> ```

### Fetch Multiple Spreads

Batch spread reads return the bid-ask spread for several outcomes in one
request.

> [!NOTE]
>
> Maximum 500 items per request.

> [tab] TypeScript
>
> Call `fetchSpreads()` on a `PublicClient` or `SecureClient` to fetch several spreads
> in one request.
>
> ```ts theme={null}
> const spreads = await client.fetchSpreads([
>   { assetId: yesAssetId },
>   { assetId: noAssetId },
> ]);
>
> // spreads: Spreads
> ```
>
> The result maps each outcome identifier to its spread:
>
> ```ts Spreads Type theme={null}
> type Spreads = Record<ClobAssetId, DecimalString>;
> ```
>
> ```json Spreads Example theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.01",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.02"
> }
> ```

> [tab] Python
>
> Call `get_spreads()` on an `AsyncPublicClient` or `AsyncSecureClient` to
> fetch several spreads in one request. The synchronous `PublicClient` and
> `SecureClient` provide the same method.
>
> ```python theme={null}
> spreads = await client.get_spreads(asset_ids=[yes_asset_id, no_asset_id])
>
> # spreads: dict[ClobAssetId, Decimal]
> ```
>
> The result maps each outcome identifier to its spread:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.01",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.02"
> }
> ```

> [tab] API
>
> Fetch several spreads in one request:
>
> ```bash theme={null}
> curl -X POST "https://clob.polymarket.com/spreads" \
>   -H "Content-Type: application/json" \
>   --data '[{"token_id":"<yes_asset_id>"},{"token_id":"<no_asset_id>"}]'
> ```
>
> The response maps each outcome identifier to its spread:
>
> ```json theme={null}
> {
>   "107505882767731489358349912513945399560393482969656700824895970500493757150417": "0.01",
>   "7305630249804085635496399869905769372294302716159034447326228509068694952392": "0.02"
> }
> ```

## Last Trade Price

Use the last trade price to see where an outcome most recently traded.

### Fetch a Last Trade Price

> [tab] TypeScript
>
> Call `fetchLastTradePrice()` on a `PublicClient` or `SecureClient` to fetch the last
> trade.
>
> ```ts theme={null}
> const lastTrade = await client.fetchLastTradePrice({ assetId: yesAssetId });
>
> // lastTrade: LastTradePrice | null
> ```
>
> `LastTradePrice` pairs the traded price with its order side:
>
> ```ts LastTradePrice Type theme={null}
> type LastTradePrice = {
>   price: DecimalString;
>   side: OrderSide;
> };
> ```
>
> ```json LastTradePrice Example theme={null}
> {
>   "price": "0.08",
>   "side": "SELL"
> }
> ```
>
> When a token has never traded, `fetchLastTradePrice()` returns `null`
> instead of a `LastTradePrice` object:
>
> ```json theme={null}
> null
> ```

> [tab] Python
>
> Call `get_last_trade_price()` on an `AsyncPublicClient` or
> `AsyncSecureClient` to fetch the last trade. The synchronous `PublicClient`
> and `SecureClient` provide the same method.
>
> ```python theme={null}
> last_trade = await client.get_last_trade_price(asset_id=yes_asset_id)
>
> # last_trade: LastTradePrice | None
> ```
>
> `LastTradePrice` pairs the traded price with its order side:
>
> ```python LastTradePrice Type theme={null}
> class LastTradePrice:
>     price: Decimal
>     side: OrderSide
> ```
>
> ```json LastTradePrice Example theme={null}
> {
>   "price": "0.08",
>   "side": "SELL"
> }
> ```
>
> When a token has never traded, `get_last_trade_price()` returns `None`
> instead of a `LastTradePrice` object:
>
> ```python theme={null}
> None
> ```

> [tab] API
>
> Fetch the last trade:
>
> ```bash theme={null}
> curl "https://clob.polymarket.com/last-trade-price?token_id=$TOKEN_ID"
> ```
>
> The response contains the traded price and side:
>
> ```json theme={null}
> {
>   "price": "0.08",
>   "side": "SELL"
> }
> ```
>
> When a token has never traded and its order book is empty, the API returns
> the `"0.5"` placeholder and an empty `side` string:
>
> ```json theme={null}
> {
>   "price": "0.5",
>   "side": ""
> }
> ```

### Fetch Multiple Last Trade Prices

Fetch the most recent matched trade for several outcomes in one request.

> [!NOTE]
>
> Maximum 500 items per request.

> [tab] TypeScript
>
> Call `fetchLastTradePrices()` on a `PublicClient` or `SecureClient` to fetch several
> last trades.
>
> ```ts theme={null}
> const lastTrades = await client.fetchLastTradePrices([
>   { assetId: yesAssetId },
>   { assetId: noAssetId },
> ]);
>
> // lastTrades: LastTradePriceForAsset[]
> ```
>
> Each `LastTradePriceForAsset` identifies the outcome alongside its traded
> price and side:
>
> ```ts LastTradePriceForAsset Type theme={null}
> type LastTradePriceForAsset = {
>   assetId: ClobAssetId;
>   price: DecimalString;
>   side: OrderSide;
> };
> ```
>
> ```json LastTradePriceForAsset Example theme={null}
> [
>   {
>     "assetId": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>     "price": "0.08",
>     "side": "SELL"
>   },
>   {
>     "assetId": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
>     "price": "0.91",
>     "side": "BUY"
>   }
> ]
> ```

> [tab] Python
>
> Call `get_last_trade_prices()` on an `AsyncPublicClient` or
> `AsyncSecureClient` to fetch several last trades. The synchronous
> `PublicClient` and `SecureClient` provide the same method.
>
> ```python theme={null}
> last_trades = await client.get_last_trade_prices(
>     asset_ids=[yes_asset_id, no_asset_id]
> )
>
> # last_trades: tuple[LastTradePriceForAsset, ...]
> ```
>
> Each `LastTradePriceForAsset` identifies the outcome alongside its traded
> price and side:
>
> ```python LastTradePriceForAsset Type theme={null}
> class LastTradePriceForAsset:
>     asset_id: ClobAssetId
>     price: Decimal
>     side: OrderSide
> ```
>
> ```json LastTradePriceForAsset Example theme={null}
> [
>   {
>     "asset_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>     "price": "0.08",
>     "side": "SELL"
>   },
>   {
>     "asset_id": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
>     "price": "0.91",
>     "side": "BUY"
>   }
> ]
> ```

> [tab] API
>
> Fetch several last trade prices in one request:
>
> ```bash theme={null}
> curl -X POST "https://clob.polymarket.com/last-trades-prices" \
>   -H "Content-Type: application/json" \
>   --data '[{"token_id":"<yes_asset_id>"},{"token_id":"<no_asset_id>"}]'
> ```
>
> The response identifies each outcome alongside its traded price and side:
>
> ```json theme={null}
> [
>   {
>     "token_id": "107505882767731489358349912513945399560393482969656700824895970500493757150417",
>     "price": "0.08",
>     "side": "SELL"
>   },
>   {
>     "token_id": "7305630249804085635496399869905769372294302716159034447326228509068694952392",
>     "price": "0.91",
>     "side": "BUY"
>   }
> ]
> ```

Outcomes that have never traded are omitted from the batch response.

## Price History

Read historical prices for an outcome token over a selected time period.

> [tab] TypeScript
>
> Call `listPriceHistory()` on a `PublicClient` or `SecureClient`. Choose a
> relative window, an explicit time range, or a point in time.
>
> ```ts Relative Window theme={null}
> import { PriceHistoryInterval } from "@polymarket/client";
>
> const pages = client.listPriceHistory({
>   assetId: yesAssetId,
>   interval: PriceHistoryInterval.OneDay,
>   bucketSeconds: 3600,
> });
>
> for await (const page of pages) {
>   // page.items: PriceHistoryPoint[]
> }
> ```
>
> ```ts Absolute Range theme={null}
> const pages = client.listPriceHistory({
>   assetId: yesAssetId,
>   start: 1788278400,
>   end: 1788364800,
>   bucketSeconds: 3600,
> });
>
> for await (const page of pages) {
>   // page.items: PriceHistoryPoint[]
> }
> ```
>
> ```ts Point In Time theme={null}
> const pages = client.listPriceHistory({
>   assetId: yesAssetId,
>   asOf: 1788364800,
> });
> const observation = await pages.firstPage();
>
> // observation.items: PriceHistoryPoint[] (at most one item)
> ```
>
> Each `PriceHistoryPoint` carries the observation time in epoch
> milliseconds, the price as a decimal string, and the window it was
> observed in:
>
> > [accordion] Output: PriceHistoryPoint
> >
> > ```ts PriceHistoryPoint Type theme={null}
> > type PriceHistoryPoint = {
> >   /** Observation time as Unix epoch milliseconds. */
> >   timestamp: EpochMilliseconds;
> >   /** Observed price, normalized to a decimal string. */
> >   price: DecimalString;
> >   /** Width of the observation window in seconds; zero identifies an exact tick. */
> >   resolutionSeconds: number;
> > };
> > ```
> >
> > ```json PriceHistoryPoint Example theme={null}
> > [
> >   {
> >     "timestamp": 1788354000000,
> >     "price": "0.255",
> >     "resolutionSeconds": 3600
> >   },
> >   {
> >     "timestamp": 1788357600000,
> >     "price": "0.255",
> >     "resolutionSeconds": 3600
> >   },
> >   {
> >     "timestamp": 1788361200000,
> >     "price": "0.255",
> >     "resolutionSeconds": 3600
> >   }
> > ]
> > ```
>
> Points are oldest first. The final observation can fall between bucket
> boundaries. Read `resolutionSeconds` instead of assuming uniform spacing.
>
> > [accordion] History Windows and Resolution
> >
> > - Explicit `start`/`end` ranges span at most 15 days. `start` is inclusive and `end` exclusive.
> > - `PriceHistoryInterval.Max` returns full history at 12-hour buckets by default. Explicit `bucketSeconds` values of 10800 or 43200 also cover full history. Finer widths return only the last 30 days.
> > - `bucketSeconds` accepts 60 to 86400 seconds, with a floor of 600 for `max`/`1m` and 300 for `1w`. Omit it to let the server choose a width for the span and available history.
> > - One-minute data lasts at least 7 days, five-minute at least 60 days, and thirty-minute at least 90 days (floors, not exact horizons). Three-hour and twelve-hour data is permanent. Explicitly requesting a resolution the store cannot fill returns an empty or sparse page with `resolution_seconds` echoing the requested grid; omit `bucket_seconds` to always get the densest series that exists.

> [tab] Python
>
> Call `list_price_history()` on an existing `AsyncPublicClient` or `AsyncSecureClient`.
>
> Choose a relative window, an explicit time range, or a point in time.
>
> ```python Relative Window theme={null}
> pages = client.list_price_history(
>     asset_id=yes_asset_id,
>     interval="1d",
>     bucket_seconds=3600,
> )
>
> async for page in pages:
>     # page.items: tuple[PriceHistoryPoint, ...]
>     pass
> ```
>
> ```python Absolute Range theme={null}
> pages = client.list_price_history(
>     asset_id=yes_asset_id,
>     start=1788278400,
>     end=1788364800,
>     bucket_seconds=3600,
> )
>
> async for page in pages:
>     # page.items: tuple[PriceHistoryPoint, ...]
>     pass
> ```
>
> ```python Point in Time theme={null}
> pages = client.list_price_history(
>     asset_id=yes_asset_id,
>     as_of=1788364800,
> )
> page = await pages.first_page()
> observation = page.items[0] if page.items else None
>
> # observation: PriceHistoryPoint | None
> ```
>
> > [accordion] Output: PriceHistoryPoint
> >
> > ```python PriceHistoryPoint Type theme={null}
> > class PriceHistoryPoint:
> >     timestamp: datetime
> >     price: Decimal
> >     resolution_seconds: int
> > ```
> >
> > ```json PriceHistoryPoint Example theme={null}
> > {
> >   "timestamp": "2026-09-07T17:04:00Z",
> >   "price": "0.955",
> >   "resolution_seconds": 60
> > }
> > ```
>
> Points are ordered oldest first. `timestamp` is a timezone-aware `datetime` and `price` is a `Decimal`. `resolution_seconds` is the observation window in seconds, with zero for an exact tick.
>
> > [accordion] History Windows and Resolution
> >
> > - Explicit ranges span at most 15 days. `start` is inclusive and `end` is exclusive.
> > - Choose exactly one of `interval`, `start`, or `as_of`. An `as_of` request cannot set `bucket_seconds` or `page_size`.
> > - `bucket_seconds` accepts 60 to 86400 seconds. The minimum is 600 for `max`, `all`, and `1m`, and 300 for `1w`. Omit it to let the service choose the resolution.
> > - Use `interval="max"` without `bucket_seconds` for full history at the default resolution.

> [tab] API
>
> Pass `token_id` and exactly one time form: `interval` for a relative
> window, `start` (with optional `end`, epoch seconds, at most 15 days) for
> an absolute range, or `as_of` for a point-in-time read. `bucket_seconds`
> sets the bucket width in seconds; deeper pages come from `?cursor=`.
>
> ```bash Relative Window theme={null}
> curl "https://data-api.polymarket.com/v2/prices-history?token_id=$TOKEN_ID&interval=1d&bucket_seconds=3600"
> ```
>
> ```bash Absolute Range theme={null}
> curl "https://data-api.polymarket.com/v2/prices-history?token_id=$TOKEN_ID&start=1788278400&end=1788364800&bucket_seconds=3600"
> ```
>
> ```bash Point In Time theme={null}
> curl "https://data-api.polymarket.com/v2/prices-history?token_id=$TOKEN_ID&as_of=1788364800"
> ```
>
> The response contains the price points under `data`, oldest first, with
> the cursor pagination object:
>
> ```json theme={null}
> {
>   "data": [
>     { "timestamp": 1788354000, "price": 0.255, "resolution_seconds": 3600 },
>     { "timestamp": 1788357600, "price": 0.255, "resolution_seconds": 3600 },
>     { "timestamp": 1788361200, "price": 0.255, "resolution_seconds": 3600 }
>   ],
>   "pagination": {
>     "limit": 3,
>     "has_more": true,
>     "next_cursor": "eyJkYXRhIjp7InR5cGUiOiJwcmljZXNfaGlzdG9yeSI…"
>   }
> }
> ```
>
> Points are oldest first. The final observation can fall between bucket
> boundaries. Read `resolution_seconds` instead of assuming uniform spacing.
>
> > [accordion] History Windows and Resolution
> >
> > - Explicit `start`/`end` ranges span at most 15 days. `start` is inclusive and `end` exclusive.
> > - `max` returns full history at 12-hour buckets by default. Explicit `bucket_seconds` values of 10800 or 43200 also cover full history. Finer widths return only the last 30 days.
> > - `bucket_seconds` accepts 60 to 86400 seconds, with a floor of 600 for `max`/`1m` and 300 for `1w`. Omit it to let the server choose a width for the span and available history.
> > - One-minute data lasts at least 7 days, five-minute at least 60 days, and thirty-minute at least 90 days (floors, not exact horizons). Three-hour and twelve-hour data is permanent. Explicitly requesting a resolution the store cannot fill returns an empty or sparse page with `resolution_seconds` echoing the requested grid; omit `bucket_seconds` to always get the densest series that exists.

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.
