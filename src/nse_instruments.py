"""Static NSE symbol -> Upstox instrument-key mapping.

Upstox's market-quote API has no symbol search; each instrument must be
addressed by its ``NSE_EQ|<ISIN>`` key. Keys are looked up once from Upstox's
public instrument master (``https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz``,
column ``instrument_key`` where ``instrument_type == "EQUITY"`` and
``tradingsymbol`` matches) and hardcoded here, since ISINs for listed equities
do not change.

To add a symbol: download that CSV, find the row for the symbol, and add its
``instrument_key`` below.
"""

from __future__ import annotations

# fmt: off
SYMBOL_TO_INSTRUMENT_KEY: dict[str, str] = {
    # Default portfolio (src.config.DEFAULT_PORTFOLIO_STOCKS)
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "INFY": "NSE_EQ|INE009A01021",
    # User portfolio (added 2026-09-29)
    "AARTIIND": "NSE_EQ|INE769A01020",
    "ADANIPORTS": "NSE_EQ|INE742F01042",
    "BAJFINANCE": "NSE_EQ|INE296A01032",
    "BALRAMCHIN": "NSE_EQ|INE119A01028",
    "BHEL": "NSE_EQ|INE257A01026",
    "DMART": "NSE_EQ|INE192R01011",
    "FSL": "NSE_EQ|INE684F01012",
    "INDUSINDBK": "NSE_EQ|INE095A01012",
    "IOC": "NSE_EQ|INE242A01010",
    "JPPOWER": "NSE_EQ|INE351F01018",
    "MANAPPURAM": "NSE_EQ|INE522D01027",
    "NATIONALUM": "NSE_EQ|INE139A01034",
    "PFC": "NSE_EQ|INE134E01011",
    "PHOENIXLTD": "NSE_EQ|INE211B01039",
    "PNBHOUSING": "NSE_EQ|INE572E01012",
    "POWERGRID": "NSE_EQ|INE752E01010",
    "RECLTD": "NSE_EQ|INE020B01018",
}
# fmt: on
