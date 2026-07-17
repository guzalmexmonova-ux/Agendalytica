#!/usr/bin/env python3
"""
ПРОВЕРКА КАНДИДАТОВ — авторитетные первоисточники взамен мёртвых.
Ничего не добавляет в парсер. Только проверяет: живой / мёртвый / свежий.
В parser.py пойдут ТОЛЬКО те, что прошли проверку.
"""

import time
from datetime import datetime, timezone

import feedparser

CANDIDATES = [
    # ═══ 1. АГЕНТСТВА — нулевая секунда ═══
    ("Reuters via GNews", "https://news.google.com/rss/search?q=site:reuters.com+when:6h&hl=en-US&gl=US&ceid=US:en"),
    ("AP via GNews", "https://news.google.com/rss/search?q=site:apnews.com+when:6h&hl=en-US&gl=US&ceid=US:en"),
    ("AP direct", "https://apnews.com/index.rss"),
    ("AFP via GNews", "https://news.google.com/rss/search?q=site:afp.com+OR+site:barrons.com/afp+when:12h&hl=en-US"),
    ("Bloomberg politics", "https://feeds.bloomberg.com/politics/news.rss"),
    ("Bloomberg tech", "https://feeds.bloomberg.com/technology/news.rss"),
    ("Bloomberg via GNews", "https://news.google.com/rss/search?q=site:bloomberg.com+when:6h&hl=en-US"),

    # ═══ 2. АНАЛИТИКА И ЧАСТНАЯ РАЗВЕДКА ═══
    ("Stratfor", "https://worldview.stratfor.com/feeds/all"),
    ("Geopolitical Futures", "https://geopoliticalfutures.com/feed/"),
    ("Foreign Policy", "https://foreignpolicy.com/feed/"),
    ("Chatham House", "https://www.chathamhouse.org/rss/all"),
    ("RUSI", "https://www.rusi.org/rss.xml"),
    ("CSIS", "https://www.csis.org/rss/analysis"),
    ("Carnegie", "https://carnegieendowment.org/rss/pubs"),
    ("War on the Rocks", "https://warontherocks.com/feed/"),
    ("ISW", "https://www.understandingwar.org/feed"),

    # ═══ 3. ФИНАНСОВАЯ ПРЕССА ═══
    ("WSJ world", "https://feeds.content.dowjones.io/public/rss/RSSWorldNews"),
    ("WSJ via GNews", "https://news.google.com/rss/search?q=site:wsj.com+when:6h&hl=en-US"),
    ("Economist", "https://www.economist.com/international/rss.xml"),
    ("Economist finance", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("FT via GNews", "https://news.google.com/rss/search?q=site:ft.com+when:6h&hl=en-US"),

    # ═══ 4. РЕГИОНАЛЬНЫЕ ═══
    ("Al-Monitor", "https://www.al-monitor.com/rss"),
    ("Al-Monitor alt", "https://www.al-monitor.com/rss.xml"),
    ("Eurasianet", "https://eurasianet.org/rss.xml"),
    ("Eurasianet via GNews", "https://news.google.com/rss/search?q=site:eurasianet.org+when:24h&hl=en-US"),
    ("Nikkei Asia alt", "https://asia.nikkei.com/rss/feed/nar"),
    ("Kyiv Independent", "https://kyivindependent.com/feed/"),
    ("Times of Israel", "https://www.timesofisrael.com/feed/"),

    # ═══ 5. ЗАКУЛИСЬЕ ═══
    ("Politico US", "https://rss.politico.com/politics-news.xml"),
    ("Politico congress", "https://rss.politico.com/congress.xml"),
    ("Politico EU", "https://www.politico.eu/feed/"),
    ("Axios", "https://api.axios.com/feed/"),
    ("Axios world", "https://api.axios.com/feed/world"),

    # ═══ 6. КРУПНЫЕ ИЗДАНИЯ ═══
    ("Guardian World", "https://www.theguardian.com/world/rss"),
    ("DW World", "https://rss.dw.com/rdf/rss-en-world"),
    ("France24", "https://www.france24.com/en/rss"),
    ("NPR World", "https://feeds.npr.org/1004/rss.xml"),
    ("CNBC World", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),

    # ═══ 7. ОФИЦИАЛЬНЫЕ: США ═══
    ("White House", "https://www.whitehouse.gov/feed/"),
    ("State Dept", "https://www.state.gov/rss-feed/press-releases/feed/"),
    ("Pentagon news", "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=20"),
    ("OFAC actions", "https://ofac.treasury.gov/system/files/rss/recent-actions.xml"),
    ("Treasury press", "https://home.treasury.gov/news/press-releases/feed"),
    ("EIA energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("SEC press", "https://www.sec.gov/news/pressreleases.rss"),

    # ═══ 8. ОФИЦИАЛЬНЫЕ: МЕЖДУНАРОДНЫЕ ═══
    ("IMF news", "https://www.imf.org/en/News/RSS?language=eng"),
    ("BIS press", "https://www.bis.org/list/pressrels/rss.xml"),
    ("NATO news", "https://www.nato.int/cps/en/natohq/rss_news.xml"),
    ("IAEA", "https://www.iaea.org/feeds/topnews"),
    ("EU Commission", "https://ec.europa.eu/commission/presscorner/api/rss?language=en&pagesize=20"),
    ("OPEC", "https://www.opec.org/opec_web/en/rss/press_releases.xml"),
    ("World Bank", "https://www.worldbank.org/en/news/all.rss"),
    ("BoE", "https://www.bankofengland.co.uk/rss/news"),
]


def check(name, url):
    try:
        f = feedparser.parse(url, agent="Mozilla/5.0",
                            request_headers={"Cache-Control": "no-cache"})
        status = getattr(f, "status", None)
        n = len(f.entries)
        if status and status >= 400:
            return False, f"{name:<20} ❌ HTTP {status}"
        if n == 0:
            return False, f"{name:<20} ❌ пусто"
        ages, now = [], datetime.now(timezone.utc)
        for e in f.entries[:10]:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if pub:
                ages.append((now - datetime(*pub[:6], tzinfo=timezone.utc)).total_seconds() / 60)
        if ages:
            fresh = round(min(ages))
            unit = f"{fresh}м" if fresh < 1440 else f"{round(fresh/1440)}д"
            return True, f"{name:<20} ✅ {n:>3} зап | свежая: {unit}"
        return True, f"{name:<20} ⚠ {n:>3} зап | без дат"
    except Exception as e:
        return False, f"{name:<20} ❌ {str(e)[:35]}"


def main():
    print(f"🔍 Проверяю {len(CANDIDATES)} кандидатов\n")
    ok = []
    for name, url in CANDIDATES:
        good, line = check(name, url)
        print(line)
        if good:
            ok.append((name, url))
        time.sleep(1.5)

    print("\n" + "=" * 55)
    print(f"✅ Годных: {len(ok)}/{len(CANDIDATES)}")
    print("=" * 55)
    print("\nURL прошедших проверку:\n")
    for name, url in ok:
        print(f'  {name}\n    {url}')


if __name__ == "__main__":
    main()
