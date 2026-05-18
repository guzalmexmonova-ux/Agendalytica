#!/usr/bin/env python3
"""
AGENDALYTICA — PARSER
Собирает новости → сортирует по вирусности → сохраняет в GitHub Gist
Запускается каждые 15 минут через GitHub Actions
"""

import feedparser
import requests
import hashlib
import json
import re
import os
from datetime import datetime, timezone, timedelta

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  КОНФИГ — из GitHub Secrets
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIST_TOKEN   = os.environ.get("GIST_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")  # заполнится после первого запуска

HOURS_WINDOW = 2
MIN_SCORE    = 5
TOP_N        = 50  # Сохраняем топ-50 для анализа

TZ = timezone(timedelta(hours=5))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ИСТОЧНИКИ GDELT (RSS формат)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GDELT_FEEDS = [
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict+OR+war+OR+military+OR+invasion+OR+nuclear+OR+missile+OR+coup)&mode=artlist&maxrecords=75&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Ukraine+OR+Russia+OR+Zelensky+OR+Putin)&mode=artlist&maxrecords=75&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Israel+OR+Gaza+OR+Iran+OR+Houthi)&mode=artlist&maxrecords=75&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Taiwan+OR+China+OR+semiconductor+OR+chip+ban)&mode=artlist&maxrecords=50&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Federal+Reserve+OR+ECB+OR+rate+hike+OR+recession)&mode=artlist&maxrecords=50&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(gold+OR+oil+OR+brent+OR+OPEC+OR+uranium)&mode=artlist&maxrecords=75&format=rss&timespan=2h", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Uzbekistan+OR+Kazakhstan+OR+Kyrgyzstan+OR+Tajikistan)&mode=artlist&maxrecords=50&format=rss&timespan=2h", 3),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(summit+OR+state+visit+OR+bilateral+talks+OR+G7+OR+G20)&mode=artlist&maxrecords=50&format=rss&timespan=2h", 3),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(terrorist+attack+OR+explosion+OR+coup+OR+assassination)&mode=artlist&maxrecords=50&format=rss&timespan=2h", 4),
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RSS ИСТОЧНИКИ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RSS_FEEDS = [
    {"url": "https://feeds.reuters.com/reuters/topNews",                                                          "source": "Reuters",        "weight": 4},
    {"url": "https://apnews.com/rss",                                                                             "source": "AP News",        "weight": 4},
    {"url": "https://feeds.bloomberg.com/markets/news.rss",                                                       "source": "Bloomberg",      "weight": 4},
    {"url": "https://www.ft.com/world?format=rss",                                                                "source": "FT",             "weight": 4},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                                                       "source": "WSJ",            "weight": 4},
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml",                                                 "source": "FED",            "weight": 4},
    {"url": "https://www.imf.org/en/news/rss",                                                                    "source": "IMF",            "weight": 4},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                                        "source": "BBC World",      "weight": 3},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",                                                          "source": "Al Jazeera",     "weight": 3},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",                                            "source": "NYT",            "weight": 3},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",                                             "source": "CNBC",           "weight": 3},
    {"url": "https://asia.nikkei.com/rss/feed/nar",                                                               "source": "Nikkei",         "weight": 3},
    {"url": "https://www.scmp.com/rss/91/feed",                                                                   "source": "SCMP",           "weight": 3},
    {"url": "https://tass.ru/rss/v2.xml",                                                                         "source": "TASS",           "weight": 3},
    {"url": "https://eurasianet.org/feed",                                                                        "source": "EurasiaNet",     "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/bbbreaking",                                                                "source": "TG Bloomberg",   "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/ReutersWorld",                                                              "source": "TG Reuters",     "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/tass_agency",                                                               "source": "TG TASS",        "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rian_ru",                                                                   "source": "TG RIA",         "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rbc_news",                                                                  "source": "TG RBC",         "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/interfaxonline",                                                            "source": "TG Interfax",    "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/militarynews",                                                              "source": "TG Military",    "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/oilgas",                                                                    "source": "TG Oil&Gas",     "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/market_twits",                                                              "source": "TG Markets",     "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/intelslava",                                                                "source": "TG Intel",       "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/iranintl",                                                                  "source": "TG IranIntl",    "weight": 3},
    {"url": "https://news.google.com/rss/search?q=trump+OR+putin+OR+zelensky+when:2h&hl=en-US",                 "source": "GNews Leaders",  "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Federal+Reserve+ECB+rate+decision+when:2h&hl=en-US",          "source": "GNews FED",      "weight": 3},
    {"url": "https://news.google.com/rss/search?q=gold+XAU+oil+brent+OPEC+when:2h&hl=en-US",                   "source": "GNews Commod",   "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Uzbekistan+Mirziyoyev+Kazakhstan+when:2h&hl=en-US",           "source": "GNews CA",       "weight": 3},
    {"url": "https://truthsocial.com/@realDonaldTrump/feed.rss",                                                  "source": "Trump/Truth",    "weight": 5},
    {"url": "https://nitter.net/realDonaldTrump/rss",                                                             "source": "Trump/X",        "weight": 5},
    {"url": "https://nitter.net/ZelenskyyUa/rss",                                                                 "source": "Zelensky/X",     "weight": 4},
    {"url": "https://nitter.net/NATO/rss",                                                                        "source": "NATO/X",         "weight": 4},
    {"url": "https://nitter.net/KremlinRussia_E/rss",                                                            "source": "Kremlin/X",      "weight": 4},
    {"url": "https://nitter.net/MFA_China/rss",                                                                   "source": "ChinaMFA/X",     "weight": 4},
    {"url": "https://nitter.net/federalreserve/rss",                                                              "source": "FedReserve/X",   "weight": 4},
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СКОРИНГ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KEYWORDS = {
    "critical": [
        "war","invasion","nuclear","airstrike","missile","explosion","coup","assassination",
        "default","market crash","collapse","rate hike","rate cut","oil crash","chip ban",
        "cyberattack","mobilization","martial law","drone strike","blockade",
        "война","вторжение","ядерн","авиаудар","ракета","взрыв","переворот","покушение",
        "дефолт","обвал","коллапс","повышение ставки","кибератака","мобилизация",
    ],
    "financial": [
        "xauusd","gold surges","gold hits","opec cut","opec+","uranium","recession",
        "inflation surge","sovereign debt","bond yields","bank run","lng","rare earth",
        "нефть упала","золото выросло","рецессия","госдолг","спг","редкоземельн",
    ],
    "high": [
        "sanctions","escalation","ceasefire","ultimatum","summit","resignation","scandal",
        "iran nuclear","taiwan strait","brics","trade war","tariff",
        "санкции","эскалация","перемирие","ультиматум","саммит","отставка","скандал",
    ],
    "geo": [
        "trump","putin","xi jinping","netanyahu","zelensky","mirziyoyev","tokayev","erdogan",
        "трамп","путин","зеленский","мирзиёев","токаев","эрдоган",
        "russia","china","usa","iran","ukraine","israel","taiwan","nato","brics","fed","ecb",
        "россия","китай","сша","украина","израиль","тайвань","нато","фрс",
    ],
    "context": [
        "economy","trade","dollar","oil","gas","gold","inflation","military","energy",
        "экономика","торговля","доллар","нефть","газ","золото","инфляция","военн",
    ],
}
WEIGHTS = {"critical": 3, "financial": 3, "high": 2, "geo": 2, "context": 1}

TIER1_DOMAINS = {"reuters.com","bloomberg.com","ft.com","wsj.com","apnews.com","federalreserve.gov","imf.org"}
NOISE_DOMAINS = {"msn.com","buzzfeed.com","dailymail.co.uk","fxstreet.com","fxempire.com","yahoo.com","tmz.com"}
NOISE_PATTERNS = [
    "recipe","кофе","barista","restaurant","food","beer","wine","chef",
    "vacation","hotel","resort","soccer goal","basketball","nba draft",
    "celebrity","hollywood","grammy","oscar","music video","red carpet",
    "seo tips","digital marketing","horoscope","гороскоп",
    "on our radar","week in review","monthly roundup","annual report",
    "everything you need to know","deep dive","explainer:",
]

def make_hash(url): return hashlib.md5(url.encode()).hexdigest()
def extract_domain(url):
    m = re.search(r'https?://(?:www\.)?([^/]+)', url or "")
    return m.group(1).lower() if m else ""
def clean_html(text): return re.sub(r'<[^>]+>', '', text or '').strip()

def score_article(title, domain=""):
    tl = title.lower()
    for p in NOISE_PATTERNS:
        if p in tl: return 0
    if domain in NOISE_DOMAINS: return 0
    text = tl
    raw = sum(WEIGHTS[cat] for cat, kws in KEYWORDS.items() for kw in kws if kw in text)
    if domain in TIER1_DOMAINS: raw += 1
    return min(10, raw)

def fetch_all():
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_WINDOW)
    seen_hashes = set()

    # GDELT
    for url, weight in GDELT_FEEDS:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0")
            for e in feed.entries[:30]:
                link = (e.get("link") or "").strip()
                if not link: continue
                h = make_hash(link)
                if h in seen_hashes: continue
                title = clean_html(e.get("title","")).strip()
                domain = extract_domain(link)
                if not title or domain in NOISE_DOMAINS: continue
                score = score_article(title, domain)
                if score < MIN_SCORE: continue
                seen_hashes.add(h)
                articles.append({
                    "hash": h, "title": title, "summary": "",
                    "link": link, "source": f"GDELT/{domain}",
                    "score": score, "weight": weight, "status": "new",
                    "ts": datetime.now(TZ).isoformat(),
                })
        except: pass

    # RSS
    for cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(cfg["url"], agent="Mozilla/5.0")
            for e in feed.entries[:20]:
                link = (e.get("link") or "").strip()
                if not link: continue
                h = make_hash(link)
                if h in seen_hashes: continue
                domain = extract_domain(link)
                if domain in NOISE_DOMAINS: continue
                pub = e.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff: continue
                title   = clean_html(e.get("title","")).strip()
                summary = clean_html(e.get("summary",""))[:400]
                if not title: continue
                score = score_article(title + " " + summary, domain)
                if score < MIN_SCORE: continue
                seen_hashes.add(h)
                articles.append({
                    "hash": h, "title": title, "summary": summary,
                    "link": link, "source": cfg["source"],
                    "score": score, "weight": cfg["weight"], "status": "new",
                    "ts": datetime.now(TZ).isoformat(),
                })
        except: pass

    # Сортировка по score × weight
    articles.sort(key=lambda x: x["score"] * x["weight"], reverse=True)

    # Дедупликация по заголовку
    unique, seen_titles = [], set()
    for a in articles:
        key = re.sub(r'[^a-zа-я0-9]', '', a["title"].lower())[:50]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(a)

    return unique[:TOP_N]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GIST — хранилище между скриптами
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def gist_read(gist_id, filename):
    try:
        r = requests.get(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            timeout=10
        )
        if r.status_code == 200:
            content = r.json()["files"].get(filename, {}).get("content", "")
            return json.loads(content) if content else {}
    except: pass
    return {}

def gist_write(gist_id, filename, data):
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            json={"files": {filename: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}},
            timeout=10
        )
        return r.status_code == 200
    except: return False

def gist_create(description):
    try:
        r = requests.post(
            "https://api.github.com/gists",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            json={
                "description": description,
                "public": False,
                "files": {
                    "queue.json":    {"content": "{}"},
                    "analyzed.json": {"content": "{}"},
                    "sent.json":     {"content": "{}"},
                }
            },
            timeout=10
        )
        if r.status_code == 201:
            return r.json()["id"]
    except: pass
    return None

def get_or_create_gist():
    """Находит или создаёт Gist для хранения данных"""
    if GIST_ID:
        return GIST_ID
    # Ищем существующий Gist
    try:
        r = requests.get(
            "https://api.github.com/gists",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            timeout=10
        )
        if r.status_code == 200:
            for gist in r.json():
                if gist.get("description") == "agendalytica_data":
                    return gist["id"]
    except: pass
    # Создаём новый
    gid = gist_create("agendalytica_data")
    if gid:
        print(f"✅ Создан новый Gist: {gid}")
        print(f"   Добавь в GitHub Secrets: GIST_ID = {gid}")
    return gid

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"🔄 Parser запущен — {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} TASHKENT")

    gist_id = get_or_create_gist()
    if not gist_id:
        print("❌ Не удалось получить Gist ID")
        return

    # Читаем уже отправленные
    sent = gist_read(gist_id, "sent.json")
    sent_hashes = set(sent.get("hashes", []))

    # Читаем очередь (уже найденные, ждут анализа)
    queue = gist_read(gist_id, "queue.json")
    queue_items = queue.get("items", [])
    queue_hashes = {a["hash"] for a in queue_items}

    # Собираем новые статьи
    print(f"📡 Парсинг источников...")
    articles = fetch_all()
    print(f"✅ Найдено {len(articles)} статей")

    # Добавляем только новые (не в очереди и не отправленные)
    added = 0
    for a in articles:
        if a["hash"] not in sent_hashes and a["hash"] not in queue_hashes:
            queue_items.append(a)
            added += 1

    # Держим очередь не больше 100 статей (топ по вирусности)
    queue_items.sort(key=lambda x: x["score"] * x["weight"], reverse=True)
    queue_items = queue_items[:100]

    # Сохраняем очередь в Gist
    ok = gist_write(gist_id, "queue.json", {
        "updated": datetime.now(TZ).isoformat(),
        "items": queue_items
    })

    if ok:
        print(f"✅ Очередь обновлена: +{added} новых, всего {len(queue_items)} статей")
        # Показываем топ-3
        for i, a in enumerate(queue_items[:3], 1):
            print(f"  [{i}] {a['score']}/10 [{a['source']}] {a['title'][:70]}")
    else:
        print("❌ Ошибка записи в Gist")

if __name__ == "__main__":
    main()
