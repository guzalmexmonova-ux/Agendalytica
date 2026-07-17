#!/usr/bin/env python3
"""
ПЕРЕПРОВЕРКА GDELT и TG — последовательно, с паузами.
Первая диагностика била в 12 потоков и получила 429 (лимит хоста),
а не реальную смерть фидов. Здесь — по одному, как в парсере.
"""

import time
from datetime import datetime, timezone

import feedparser

from parser import GDELT_FEEDS, RSS_FEEDS


def check(url, name):
    try:
        f = feedparser.parse(url, agent="Mozilla/5.0",
                            request_headers={"Cache-Control": "no-cache"})
        status = getattr(f, "status", None)
        n = len(f.entries)
        if status and status >= 400:
            return f"{name:<22} ❌ HTTP {status}"
        if n == 0:
            return f"{name:<22} ⚠ пусто"
        ages, now = [], datetime.now(timezone.utc)
        for e in f.entries[:10]:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if pub:
                ages.append((now - datetime(*pub[:6], tzinfo=timezone.utc)).total_seconds() / 60)
        age = f"{round(min(ages))}м (самая свежая)" if ages else "без дат"
        return f"{name:<22} ✅ {n:>3} зап | {age}"
    except Exception as e:
        return f"{name:<22} ❌ {str(e)[:40]}"


def main():
    print("🐌 Последовательная проверка с паузами\n")

    print("━━━ GDELT ━━━")
    for url, name, _ in GDELT_FEEDS:
        print(check(url, name))
        time.sleep(2)

    print("\n━━━ TELEGRAM-МОСТЫ ━━━")
    tg = [c for c in RSS_FEEDS if "tg.i-c-a.su" in c["url"]]
    for c in tg:
        print(check(c["url"], c["source"]))
        time.sleep(2)


if __name__ == "__main__":
    main()
