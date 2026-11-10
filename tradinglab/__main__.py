"""
Replay the lab in the terminal, without Jarvis or Firebase:

  yarn lab --from 2026-11-03            (from the repo root)
  yarn lab --from 2026-11-03 --to 2026-11-06
"""

import argparse
import asyncio
from datetime import date, timedelta

from .lab import newest_finished, replay_day, weekdays
from .rules import MARKETS, RULES


async def main(start: str, end: str | None) -> None:
    for key, m in MARKETS.items():
        last = end or await newest_finished(key)
        if not last:
            print(f"\n{m.name}: no finished session yet")
            continue
        pots = {s: RULES.pot for s in m.stocks}
        withdrawn = 0.0
        print(f"\n══ {m.name} ({m.currency}), {start} to {last} ══")
        for day in weekdays(start, last):
            res = await replay_day(key, day, pots)
            if res is None:
                print(f"{day}  market closed")
                continue
            for s, r in res.items():
                t = r["trade"]
                if t:
                    print(f"{day}  {s:<9} buy {t['buyTime']} @ {t['buyPrice']:>10,.2f} → sell {t['sellTime']} @ {t['sellPrice']:>10,.2f}"
                          f"  {r['pnl']:+8.2f}  {t['exit']}")
                else:
                    print(f"{day}  {s:<9} no trade: {r['note']}")
                pots[s] = r["potEnd"]
                withdrawn += r["withdrawn"]
        pnl = sum(pots.values()) + withdrawn - RULES.pot * len(m.stocks)
        print(f"→ pots {sum(pots.values()):,.2f} + withdrawn {withdrawn:,.2f} = P&L {pnl:+,.2f} {m.currency}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Replay the day-trading lab")
    ap.add_argument("--from", dest="start", default=(date.today() - timedelta(days=7)).isoformat())
    ap.add_argument("--to", dest="end", default=None)
    a = ap.parse_args()
    asyncio.run(main(a.start, a.end))
