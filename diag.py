#!/usr/bin/env python3
"""
AGENDALYTICA — ДИАГНОСТИКА ФИДОВ
Прогоняет все источники из parser.py и показывает: живой / мёртвый,
сколько записей, есть ли даты, средний возраст.
Запуск: вручную через Actions (diag.yml). Ничего не пишет и не шлёт.
"""

import concurrent.futures as cf
import re
from datetime import datetime, timezone

import feedparser

from parser import GDELT_FEEDS, RSS_FEEDS


def check(url, name):
    res = {"name": name, "url": url, "n": 0, "dated": 0, "avg_age": None, "err": ""}
    try:
        f = feedparser.parse(url, agent="Mozilla/5.0",
                            request_headers={"Cache-Control": "no-cache"})
        status = getattr(f, "status", None)
        if getattr(f, "bozo", 0) and not f.entries:
            res["err"] = str(getattr(f, "bozo_exception", ""))[:60]
        if status and status >= 400:
            res["err"] = f"HTTP {status}"
        res["n"] = len(f.entries)
        ages = []
        now = datetime.now(timezone.utc)
        for e in f.entries[:20]:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if pub:
                res["dated"] += 1
                dt = datetime(*pub[:6], tzinfo=timezone.utc)
                ages.append((now - dt).total_seconds() / 60)
        if ages:
            res["avg_age"] = round(sum(ages) / len(ages))
    except Exception as e:
        res["err"] = str(e)[:60]
    return res


def main():
    feeds = [(u, n) for u, n, _ in GDELT_FEEDS] + [(c["url"], c["source"]) for c in RSS_FEEDS]
    print(f"🔍 Проверяю {len(feeds)} фидов...\n")

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda t: check(*t), feeds))

    alive = [r for r in results if r["n"] > 0]
    dead = [r for r in results if r["n"] == 0]

    print(f"{'ИСТОЧНИК':<24}{'ЗАП':>5}{'С ДАТОЙ':>9}{'ВОЗРАСТ':>10}")
    print("─" * 60)
    for r in sorted(alive, key=lambda x: x["name"]):
        age = f"{r['avg_age']}м" if r["avg_age"] is not None else "—"
        flag = "  ⚠ без дат" if r["dated"] == 0 else ""
        print(f"{r['name']:<24}{r['n']:>5}{r['dated']:>9}{age:>10}{flag}")

    print("\n💀 МЁРТВЫЕ (0 записей):")
    print("─" * 60)
    for r in sorted(dead, key=lambda x: x["name"]):
        print(f"  {r['name']:<24} {r['err'] or 'пусто'}")

    nodate = [r for r in alive if r["dated"] == 0]
    stale = [r for r in alive if r["avg_age"] and r["avg_age"] > 720]

    print("\n" + "=" * 60)
    print(f"✅ Живых:        {len(alive)}/{len(feeds)}")
    print(f"💀 Мёртвых:      {len(dead)}")
    print(f"⚠  Без дат:      {len(nodate)}  (проходят как 'свежие'!)")
    print(f"🕰  Старше 12ч:   {len(stale)}")
    print("=" * 60)

    if dead:
        print("\nУдалить из RSS_FEEDS:")
        print("  " + ", ".join(sorted(r["name"] for r in dead)))


if __name__ == "__main__":
    main()
