"""
The Trading Lab's rules, markets and stocks. Paper money only: this is for learning how a
rule-based day-trading strategy behaves, never for placing real orders.

The strategy (opening-range breakout with a trailing profit lock), each trading day, per stock:
1. Watch the first 15 minutes. Their highest and lowest prices are "the opening range".
2. BUY at the next minute's open once a minute closes above the range high (no new buys in
   the last hour of the session). One trade per stock per day.
3. Stop loss: the range low, but never more than 1.5% under the buy price.
4. Once the price has been 1% over the buy price, a trailing stop follows the best price
   0.5% behind it, so a winner can run but a pullback locks the profit in.
5. Anything still held is sold 15 minutes before the close: nothing is held overnight.

Money: each stock has its own pot of 1,000 in its own currency (₹ for NSE, $ for US).
Profit from a winning day is withdrawn, so a pot never grows past 1,000; a loss shrinks it.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Rules:
    pot: float = 1000.0              # per stock, in the stock's own currency
    range_minutes: int = 15          # the opening range
    max_stop_pct: float = 1.5        # stop loss: range low, but no further than this under the buy
    trail_after_pct: float = 1.0     # trailing stop switches on once up this much
    trail_pct: float = 0.5           # ...and follows the best price this far behind
    no_entry_last_minutes: int = 60  # no new buys this close to the close
    exit_before_close_minutes: int = 15
    charges: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


RULES = Rules()


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    currency: str
    tz: str              # the exchange's time zone (its candle times are in it)
    open: str            # exchange local time, HH:MM
    close: str
    suffix: str          # symbol suffix on Financial Modeling Prep
    stocks: tuple[str, ...]


MARKETS = {
    "IN": Market("IN", "India (NSE)", "INR", "Asia/Kolkata", "09:15", "15:30", ".NS", ("RELIANCE", "HDFCBANK", "INFY", "TCS", "ITC")),
    "US": Market("US", "United States", "USD", "America/New_York", "09:30", "16:00", "", ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL")),
}
STOCKS = {s: m for m in MARKETS.values() for s in m.stocks}   # symbol -> its market


def charges(market: str, side: str, value: float, qty: float, rules: Rules = RULES) -> float:
    """Approximate costs of one intraday order, in the stock's currency.
    India (discount broker): brokerage ₹20 or 0.03% (lower), STT 0.025% on sells, exchange 0.00297%,
    SEBI 0.0001%, stamp duty 0.003% on buys, 18% GST on brokerage and fees.
    US (zero-commission broker): SEC fee 0.00278% and FINRA TAF $0.000166/share, on sells only."""
    if not rules.charges or value <= 0:
        return 0.0
    if market == "IN":
        brokerage = min(20.0, value * 0.0003)
        fees = value * 0.0000297 + value * 0.000001
        total = brokerage + fees + 0.18 * (brokerage + fees)
        total += value * 0.00025 if side == "sell" else value * 0.00003
        return round(total, 2)
    if side == "sell":
        return round(value * 0.0000278 + min(qty * 0.000166, 8.30), 2)
    return 0.0
