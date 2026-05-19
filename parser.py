#!/usr/bin/env python3
"""
AGENDALYTICA — PARSER v4.0 (FULL)
Все источники из parsing_skill.md + Парсинг.docx
GitHub Actions → Gist → Claude читает raw URL → анализирует

Источники:
  • GDELT (12 срезов, timespan=2h)
  • Институциональные (FED, IMF, BIS, ECB, IEA, WTO, NATO, UN, Pentagon)
  • Ведущие СМИ (Reuters, AP, Bloomberg, FT, WSJ, BBC, AJ, NYT, CNBC, Nikkei, SCMP, TASS, Lenta, ZeroHedge, Crisis Group, Foreign Affairs, The Diplomat, Eurasianet)
  • Telegram каналы via tg.i-c-a.su RSS (25 каналов)
  • Google News EN + RU (8 срезов)
  • X/Nitter — лидеры, МИД, военные, организации (22 аккаунта)
  • Truth Social — Трамп (прямой RSS)

Скоринг: 6-10 баллов из Парсинг.docx (полная таблица)
Хранение: GitHub Gist (secret) → raw URL для Claude
"""

import feedparser
import requests
import hashlib
import json
import re
import os
from datetime import datetime, timezone, timedelta

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  КОНФИГ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIST_TOKEN    = os.environ.get("GIST_TOKEN", "")
GIST_ID       = os.environ.get("GIST_ID", "")

HOURS_WINDOW  = 2        # окно свежести в часах
MIN_SCORE     = 6        # минимальный балл (из 10)
TOP_N         = 50       # топ статей в очереди

TZ = timezone(timedelta(hours=5))  # Ташкент GMT+5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  УРОВЕНЬ 1 — GDELT (12 срезов из parsing_skill.md)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GDELT_FEEDS = [
    # (url, source_name, weight)
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(conflict+OR+war+OR+military+OR+invasion+OR+airstrike+OR+missile+OR+nuclear+OR+escalation+OR+coup+OR+mobilization)&mode=artlist&maxrecords=75&format=rss&timespan=2h",
        "GDELT/CONFLICTS", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(terrorist+attack+OR+explosion+OR+bombing+OR+assassination+OR+hostage)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/TERRORISM", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(Ukraine+OR+Russia+OR+Kyiv+OR+Donbas+OR+Crimea+OR+Zelensky+OR+Putin)&mode=artlist&maxrecords=75&format=rss&timespan=2h",
        "GDELT/RUSSIA_UA", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(Israel+OR+Gaza+OR+Iran+OR+Houthi+OR+Hezbollah+OR+Red+Sea)&mode=artlist&maxrecords=75&format=rss&timespan=2h",
        "GDELT/MIDEAST", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(Taiwan+OR+Taiwan+Strait+OR+South+China+Sea+OR+semiconductor+OR+chip+ban+OR+TSMC+OR+ASML)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/TAIWAN", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(sanctions+OR+embargo+OR+export+ban+OR+blockade+OR+NATO+OR+BRICS)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/SANCTIONS", 3
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(Federal+Reserve+OR+Powell+OR+ECB+OR+Lagarde+OR+rate+hike+OR+rate+cut+OR+recession)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/FED_ECB", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(gold+OR+oil+OR+brent+OR+OPEC+OR+gas+OR+uranium+OR+LNG+OR+copper+OR+lithium)&mode=artlist&maxrecords=75&format=rss&timespan=2h",
        "GDELT/ENERGY", 4
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(cyberattack+OR+hack+OR+ransomware+OR+cyber+warfare)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/CYBER", 3
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(Uzbekistan+OR+Kazakhstan+OR+Kyrgyzstan+OR+Tajikistan+OR+Turkmenistan+OR+SCO+OR+CSTO+OR+Tashkent)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/CENTRAL_ASIA", 3
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(summit+OR+state+visit+OR+bilateral+talks+OR+diplomatic+meeting+OR+G7+OR+G20)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/SUMMITS", 3
    ),
    (
        "https://api.gdeltproject.org/api/v2/doc/doc?query=(inflation+OR+default+OR+market+crash+OR+collapse+OR+sovereign+debt+OR+bond+yields)&mode=artlist&maxrecords=50&format=rss&timespan=2h",
        "GDELT/MACRO", 4
    ),
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  УРОВЕНЬ 2-4 — RSS (институциональные + СМИ + Telegram + Google + Nitter)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RSS_FEEDS = [

    # ── УРОВЕНЬ 2: Институциональные первоисточники (вес 5) ──────────────
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml",           "source": "FED",              "weight": 5},
    {"url": "https://www.imf.org/en/news/rss",                              "source": "IMF",              "weight": 5},
    {"url": "https://www.bis.org/rss/pressrels.xml",                        "source": "BIS",              "weight": 5},
    {"url": "https://www.ecb.europa.eu/rss/press.html",                     "source": "ECB",              "weight": 5},
    {"url": "https://www.iea.org/news.xml",                                 "source": "IEA",              "weight": 4},
    {"url": "https://www.wto.org/english/news_e/news_xml_e.xml",            "source": "WTO",              "weight": 4},
    {"url": "https://www.nato.int/rss/",                                    "source": "NATO",             "weight": 5},
    {"url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml",       "source": "UN",               "weight": 4},
    {"url": "https://www.defense.gov/News/RSS/",                            "source": "Pentagon",         "weight": 5},

    # ── УРОВЕНЬ 3: Ведущие мировые СМИ (вес 4) ───────────────────────────
    {"url": "https://feeds.reuters.com/reuters/topNews",                    "source": "Reuters",          "weight": 4},
    {"url": "https://www.reuters.com/world/rss",                            "source": "Reuters World",    "weight": 4},
    {"url": "https://apnews.com/rss",                                       "source": "AP News",          "weight": 4},
    {"url": "https://feeds.bloomberg.com/markets/news.rss",                 "source": "Bloomberg",        "weight": 4},
    {"url": "https://www.ft.com/world?format=rss",                          "source": "FT",               "weight": 4},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                  "source": "WSJ",              "weight": 4},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                  "source": "BBC World",        "weight": 4},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml",                    "source": "Al Jazeera",       "weight": 3},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",       "source": "NYT World",        "weight": 3},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",        "source": "CNBC",             "weight": 3},
    {"url": "https://asia.nikkei.com/rss/feed/nar",                         "source": "Nikkei Asia",      "weight": 3},
    {"url": "https://www.scmp.com/rss/91/feed",                             "source": "SCMP",             "weight": 3},
    {"url": "https://www.crisisgroup.org/rss/139",                          "source": "Crisis Group",     "weight": 3},
    {"url": "https://www.foreignaffairs.com/rss.xml",                       "source": "Foreign Affairs",  "weight": 3},
    {"url": "https://thediplomat.com/feed",                                 "source": "The Diplomat",     "weight": 3},
    {"url": "https://eurasianet.org/feed",                                  "source": "EurasiaNet",       "weight": 3},
    {"url": "https://tass.ru/rss/v2.xml",                                   "source": "TASS",             "weight": 3},
    {"url": "https://lenta.ru/rss/news",                                    "source": "Lenta.ru",         "weight": 3},
    {"url": "https://www.zerohedge.com/fullrss2.xml",                       "source": "ZeroHedge",        "weight": 2},

    # ── УРОВЕНЬ 4: Telegram каналы via RSS bridge (вес 4/3) ──────────────
    # Breaking/Wire
    {"url": "https://tg.i-c-a.su/rss/bbbreaking",                          "source": "TG/Bloomberg",     "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/ReutersWorld",                        "source": "TG/Reuters",       "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/ftnews",                              "source": "TG/FT",            "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/tass_agency",                         "source": "TG/TASS",          "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rian_ru",                             "source": "TG/RIA",           "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rbc_news",                            "source": "TG/RBC",           "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/interfaxonline",                      "source": "TG/Interfax",      "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/market_twits",                        "source": "TG/Markets",       "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/centralasian",                        "source": "TG/CentralAsia",   "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/militarynews",                        "source": "TG/Military",      "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/oilgas",                              "source": "TG/OilGas",        "weight": 3},
    # Геополитика
    {"url": "https://tg.i-c-a.su/rss/geopolitics_live",                    "source": "TG/Geopolitics",   "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/war_monitor",                         "source": "TG/WarMonitor",    "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/intelslava",                          "source": "TG/IntelSlava",    "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rybar",                               "source": "TG/Rybar",         "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/grey_zone",                           "source": "TG/GreyZone",      "weight": 3},
    # Экономика
    {"url": "https://tg.i-c-a.su/rss/macronomics",                         "source": "TG/Macro",         "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/cbonds_news",                         "source": "TG/CBonds",        "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/investing",                           "source": "TG/Investing",     "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/federalreserve",                      "source": "TG/FedWatch",      "weight": 3},
    # Ближний Восток / Азия
    {"url": "https://tg.i-c-a.su/rss/mideastspectrum",                     "source": "TG/Mideast",       "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/iranintl",                            "source": "TG/IranIntl",      "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/chinaobservers",                      "source": "TG/China",         "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/nknewsorg",                           "source": "TG/NKNews",        "weight": 3},

    # ── Google News EN (when:2h) ──────────────────────────────────────────
    {"url": "https://news.google.com/rss/search?q=USA+China+Taiwan+military+Strait+when:2h&hl=en-US",            "source": "GNews/USA-China",  "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Federal+Reserve+OR+ECB+OR+BOE+rate+decision+when:2h&hl=en-US", "source": "GNews/CentralBanks","weight": 3},
    {"url": "https://news.google.com/rss/search?q=gold+XAU+price+surge+OR+fall+when:2h&hl=en-US",               "source": "GNews/Gold",        "weight": 3},
    {"url": "https://news.google.com/rss/search?q=brent+crude+oil+OPEC+cut+OR+crash+when:2h&hl=en-US",          "source": "GNews/Oil",         "weight": 3},
    {"url": "https://news.google.com/rss/search?q=TSMC+ASML+Nvidia+chip+ban+export+when:2h&hl=en-US",           "source": "GNews/Chips",       "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Israel+Iran+Gaza+Houthi+when:2h&hl=en-US",                    "source": "GNews/Mideast",     "weight": 3},
    {"url": "https://news.google.com/rss/search?q=breaking+war+attack+crisis+when:2h&hl=en-US",                  "source": "GNews/Breaking",    "weight": 3},
    # Google News RU
    {"url": "https://news.google.com/rss/search?q=война+санкции+мобилизация+НАТО+when:2h&hl=ru&gl=RU&ceid=RU:ru",                        "source": "GNews/RU-Geo",     "weight": 3},
    {"url": "https://news.google.com/rss/search?q=ФРС+ставка+рецессия+инфляция+нефть+when:2h&hl=ru&gl=RU&ceid=RU:ru",                   "source": "GNews/RU-Macro",   "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Узбекистан+Казахстан+Мирзиёев+Токаев+when:2h&hl=ru&gl=UZ&ceid=UZ:ru",                 "source": "GNews/RU-CA",      "weight": 3},

    # ── X/Nitter — лидеры (вес 5) ────────────────────────────────────────
    {"url": "https://nitter.net/realDonaldTrump/rss",                       "source": "Trump/X",          "weight": 5},
    {"url": "https://nitter.net/POTUS/rss",                                 "source": "POTUS/X",          "weight": 5},
    {"url": "https://nitter.net/WhiteHouse/rss",                            "source": "WhiteHouse/X",     "weight": 5},
    {"url": "https://nitter.net/ZelenskyyUa/rss",                           "source": "Zelensky/X",       "weight": 4},
    {"url": "https://nitter.net/EmmanuelMacron/rss",                        "source": "Macron/X",         "weight": 4},
    {"url": "https://nitter.net/narendramodi/rss",                          "source": "Modi/X",           "weight": 4},
    {"url": "https://nitter.net/RTErdogan/rss",                             "source": "Erdogan/X",        "weight": 4},
    {"url": "https://nitter.net/IsraeliPM/rss",                             "source": "Israel PM/X",      "weight": 4},
    {"url": "https://nitter.net/10DowningStreet/rss",                       "source": "UK PM/X",          "weight": 4},
    # МИД
    {"url": "https://nitter.net/SecRubio/rss",                              "source": "US SecState/X",    "weight": 5},
    {"url": "https://nitter.net/MFA_China/rss",                             "source": "ChinaMFA/X",       "weight": 4},
    {"url": "https://nitter.net/MFA_Russia/rss",                            "source": "RussiaMFA/X",      "weight": 4},
    {"url": "https://nitter.net/IsraeliMFA/rss",                            "source": "IsraelMFA/X",      "weight": 4},
    {"url": "https://nitter.net/MFATurkey/rss",                             "source": "TurkeyMFA/X",      "weight": 3},
    {"url": "https://nitter.net/AuswaertigesAmt/rss",                       "source": "GermanyMFA/X",     "weight": 3},
    {"url": "https://nitter.net/mfauzbekistan/rss",                         "source": "UzbMFA/X",         "weight": 3},
    # Военные
    {"url": "https://nitter.net/DeptofDefense/rss",                         "source": "Pentagon/X",       "weight": 5},
    {"url": "https://nitter.net/DefenceHQ/rss",                             "source": "UK MOD/X",         "weight": 4},
    # Организации
    {"url": "https://nitter.net/NATO/rss",                                  "source": "NATO/X",           "weight": 5},
    {"url": "https://nitter.net/UN/rss",                                    "source": "UN/X",             "weight": 4},
    {"url": "https://nitter.net/IMFNews/rss",                               "source": "IMF/X",            "weight": 4},
    {"url": "https://nitter.net/ECB/rss",                                   "source": "ECB/X",            "weight": 4},
    {"url": "https://nitter.net/federalreserve/rss",                        "source": "FedReserve/X",     "weight": 5},
    {"url": "https://nitter.net/KremlinRussia_E/rss",                       "source": "Kremlin/X",        "weight": 4},
    # Влиятельные
    {"url": "https://nitter.net/elonmusk/rss",                              "source": "Musk/X",           "weight": 3},
    {"url": "https://nitter.net/SpokespersonCHN/rss",                       "source": "ChinaSpox/X",      "weight": 4},

    # ── Truth Social — Трамп (самый высокий вес) ─────────────────────────
    {"url": "https://truthsocial.com/@realDonaldTrump/feed.rss",            "source": "Trump/Truth",      "weight": 5},
    {"url": "https://truthsocial.com/@realDonaldTrump/with_replies.rss",    "source": "Trump/TruthReply", "weight": 4},
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СКОРИНГ — полная таблица из Парсинг.docx
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Балл 10 — максимальный
SCORE_10 = [
    "nuclear", "ядерн", "nato article 5", "invasion", "вторжение",
    "assassination", "покушение", "collapse", "коллапс",
]

# Балл 9
SCORE_9 = [
    "war", "война", "coup", "переворот", "hypersonic", "гиперзвук",
    "martial law", "военное положение", "impeached", "импичмент",
    "default", "дефолт", "market crash", "обвал рынка",
    "oil crash", "нефть упала", "tsmc ban", "iran nuclear", "иран ядерн",
]

# Балл 8
SCORE_8 = [
    "attack", "атак", "escalation", "эскалац", "ballistic", "баллистическ",
    "airstrike", "авиаудар", "drone strike", "удар дрона",
    "mobilization", "мобилизац", "mutiny", "мятеж",
    "resigns", "отставк", "resignation", "step down",
    "scandal", "скандал",
    "rate hike", "rate cut", "повышение ставки", "снижение ставки",
    "recession", "рецессия",
    "gold surges", "золото выросло", "xauusd",
    "opec cut", "опек сокращ",
    "chip ban", "export ban", "запрет экспорта",
    "cyberattack", "кибератак", "cyber warfare", "кибервойна",
    "sovereign debt", "госдолг", "bond yields", "доходность облигаций",
    "powell", "пауэлл", "warsh", "уорш", "lagarde", "лагард",
    "bank run",
]

# Балл 7
SCORE_7 = [
    "missile", "ракета", "ceasefire", "перемирие",
    "blockade", "блокада", "strait", "пролив",
    "uranium", "уран", "lng", "спг",
    "rare earth", "редкоземельн", "copper", "медь", "lithium", "литий",
    "trade war", "торговая война", "tariff", "пошлин",
    "middle corridor", "срединный коридор",
    "gold hits", "gold falls", "brent falls", "xau",
    "inflation surge", "инфляция выросла",
    "fed decision",
]

# Балл 6
SCORE_6 = [
    "sanctions", "санкци", "conflict", "конфликт",
    "embargo", "эмбарго", "froze assets", "заморозил активы",
    "brics summit", "саммит брикс",
    "trump signs", "трамп подписал", "trump announces", "трамп объявил",
    "trump orders", "трамп ввёл",
    "putin orders", "путин приказал", "putin signs", "путин подписал",
    "xi jinping warns", "си цзиньпин",
    "mirziyoyev", "мирзиёев",
    "tokayev", "токаев",
    "csto", "одкб", "sco", "шос",
    "expelled ambassador", "отозвал посла",
    "cut diplomatic ties", "разорвал дипотношения",
    "issued ultimatum", "выдвинул ультиматум",
    "signed treaty", "подписал договор",
    "imposed sanctions", "ввёл санкции",
    "merz", "мерц",
    "opec+", "опек+",
    "seized assets", "изъял активы",
    "parliament voted", "конгресс проголосовал", "дума приняла",
    "no-confidence vote", "вотум недоверия",
    "cabinet reshuffle", "перестановки в правительстве",
]

SCORES_MAP = {
    10: SCORE_10,
    9:  SCORE_9,
    8:  SCORE_8,
    7:  SCORE_7,
    6:  SCORE_6,
}

# Breaking-маркеры — повышают балл на +1 (но не выше 10)
BREAKING_MARKERS = [
    "breaking", "just in", "confirmed", "urgent", "alert", "flash", "exclusive",
    "срочно", "только что", "сейчас", "экстренно", "подтверждено", "молния", "флэш",
]

# Anchor keywords — если есть хотя бы один, статья получает +2
ANCHOR_KEYWORDS = [
    "nuclear", "ядерн", "nato article 5", "invasion", "вторжение",
    "assassination", "покушение", "war", "война", "coup", "переворот",
    "hypersonic", "гиперзвук", "martial law", "военное положение",
    "default", "дефолт", "market crash", "oil crash",
    "airstrike", "авиаудар", "mobilization", "мобилизац",
    "rate hike", "rate cut", "collapse", "коллапс",
    "trump signs", "трамп подписал", "trump orders",
    "putin orders", "путин приказал",
    "powell", "пауэлл", "lagarde", "лагард",
    "brent falls", "gold surges",
]

# Tier-1 домены — надёжные первоисточники (+1 балл)
TIER1_DOMAINS = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com",
    "federalreserve.gov", "imf.org", "bis.org", "ecb.europa.eu",
    "nato.int", "defense.gov", "un.org", "iea.org", "wto.org",
    "nytimes.com", "bbc.com", "bbc.co.uk",
    "truthsocial.com",  # Трамп
}

# Мусорные домены — игнорировать
NOISE_DOMAINS = {
    "msn.com", "buzzfeed.com", "huffpost.com", "dailymail.co.uk",
    "fxstreet.com", "fxempire.com", "investopedia.com", "seekingalpha.com",
    "yahoo.com", "tmz.com", "espn.com", "bleacherreport.com",
    "kp.ru", "mk.ru", "spletnik.ru", "sports.ru", "championat.com",
    "starhit.ru", "varindia.com", "asiaone.com", "eturbonews.com",
    "benzinga.com", "ndtv.com", "entertainmentweekly.com",
    "people.com", "cosmopolitan.com", "vogue.com",
}

# Шумовые паттерны — нерелевантный контент
NOISE_PATTERNS = [
    # Еда
    "whiskey", "виски", "coffee", "кофе", "barista", "restaurant", "ресторан",
    "recipe", "рецепт", "food", "beer", "пиво", "wine", "вино", "chef",
    # Туризм
    "vacation", "отпуск", "tourism", "hotel", "resort", "курорт",
    # Спорт
    "soccer", "football goal", "basketball", "баскетбол",
    "nba draft", "nfl draft", "transfer fee", "трансфер игрок",
    # Шоу-бизнес
    "celebrity", "знаменитость", "hollywood", "box office",
    "music video", "grammy", "oscar", "emmy", "album release", "red carpet",
    # Маркетинг
    "seo tips", "digital marketing", "influencer", "инфлюенсер",
    "smartphone launch", "smartwatch", "gaming laptop",
    # Здоровье/личное
    "diet tips", "weight loss", "похудение", "yoga", "meditation",
    "horoscope", "гороскоп", "zodiac",
    # Аналитические форматы — не оперативные новости
    "week in review", "monthly roundup", "annual report", "year in review",
    "everything you need to know", "deep dive into", "a brief history",
    "итоги недели", "годовой отчёт", "история вопроса", "всё что нужно знать",
    "on our radar", "prioritising peace", "prioritizing peace",
    "how to ", "guide to", "what is ", "explainer:", "explained:", "opinion:",
    "мнение:", "колонка:", "the case for", "the case against",
]

# Аналитические маркеры в заголовке — снижают балл до 0
ANALYTICAL_MARKERS = [
    "week in review", "monthly roundup", "annual report", "year in review",
    "everything you need to know", "deep dive into", "a brief history",
    "итоги недели", "годовой отчёт", "история вопроса",
    "on our radar",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def make_hash(url):
    return hashlib.md5(url.encode()).hexdigest()

def extract_domain(url):
    m = re.search(r'https?://(?:www\.)?([^/]+)', url or "")
    return m.group(1).lower() if m else ""

def clean_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()

def score_article(title: str, summary: str = "", domain: str = "") -> int:
    """
    Скоринг по полной таблице из Парсинг.docx.
    Возвращает балл 0-10.
    """
    tl = (title + " " + summary).lower()

    # Шумовые паттерны → сразу 0
    for p in NOISE_PATTERNS:
        if p in tl:
            return 0
    # Мусорный домен → 0
    if domain in NOISE_DOMAINS:
        return 0
    # Аналитический заголовок → 0
    title_lower = title.lower()
    for am in ANALYTICAL_MARKERS:
        if am in title_lower:
            return 0

    # Базовый балл по ключевым словам (берём максимальный)
    score = 0
    for pts, kw_list in SCORES_MAP.items():
        for kw in kw_list:
            if kw in tl:
                score = max(score, pts)

    if score == 0:
        return 0

    # Breaking marker → +1
    for bm in BREAKING_MARKERS:
        if bm in tl:
            score = min(10, score + 1)
            break

    # Anchor keyword → +2 (если не достигнут балл через них)
    for ak in ANCHOR_KEYWORDS:
        if ak in tl:
            score = min(10, score + 1)
            break

    # Tier-1 домен → +1
    if domain in TIER1_DOMAINS:
        score = min(10, score + 1)

    return score


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ПАРСИНГ ВСЕХ ИСТОЧНИКОВ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_all() -> list:
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_WINDOW)
    seen_hashes = set()

    # ── GDELT ────────────────────────────────────────────────
    gdelt_ok = 0
    for url, source_name, weight in GDELT_FEEDS:
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0", request_headers={"Cache-Control": "no-cache"})
            for e in feed.entries[:30]:
                link = (e.get("link") or "").strip()
                if not link:
                    continue
                h = make_hash(link)
                if h in seen_hashes:
                    continue
                title = clean_html(e.get("title", "")).strip()
                domain = extract_domain(link)
                if not title or domain in NOISE_DOMAINS:
                    continue
                sc = score_article(title, "", domain)
                if sc < MIN_SCORE:
                    continue
                seen_hashes.add(h)
                gdelt_ok += 1
                articles.append({
                    "hash": h, "title": title, "summary": "",
                    "link": link, "source": source_name,
                    "score": sc, "weight": weight, "status": "new",
                    "ts": datetime.now(TZ).isoformat(),
                    "age_min": 0,  # GDELT не даёт точное время
                })
        except Exception as e:
            print(f"  ⚠ GDELT [{source_name}]: {e}")
    print(f"  ✓ GDELT: {gdelt_ok} статей")

    # ── RSS (все остальные уровни) ────────────────────────────
    rss_ok = 0
    rss_fail = 0
    for cfg in RSS_FEEDS:
        try:
            feed = feedparser.parse(
                cfg["url"], agent="Mozilla/5.0",
                request_headers={"Cache-Control": "no-cache"},
            )
            for e in feed.entries[:20]:
                link = (e.get("link") or "").strip()
                if not link:
                    continue
                h = make_hash(link)
                if h in seen_hashes:
                    continue
                domain = extract_domain(link)
                if domain in NOISE_DOMAINS:
                    continue
                # Проверка свежести
                pub = e.get("published_parsed") or e.get("updated_parsed")
                age_min = 0
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    age_min = round((datetime.now(timezone.utc) - pub_dt).total_seconds() / 60, 1)

                title   = clean_html(e.get("title", "")).strip()
                summary = clean_html(e.get("summary", ""))[:500]
                if not title:
                    continue
                sc = score_article(title, summary, domain)
                if sc < MIN_SCORE:
                    continue
                seen_hashes.add(h)
                rss_ok += 1
                articles.append({
                    "hash": h, "title": title, "summary": summary[:400],
                    "link": link, "source": cfg["source"],
                    "score": sc, "weight": cfg["weight"], "status": "new",
                    "ts": datetime.now(TZ).isoformat(),
                    "age_min": age_min,
                })
        except Exception as ex:
            rss_fail += 1
            # Не спамим логами по каждому фиду
    print(f"  ✓ RSS/TG/Nitter: {rss_ok} статей ({rss_fail} фидов с ошибками)")

    # ── Сортировка: score × weight, свежие приоритетнее ─────────
    articles.sort(
        key=lambda x: (x["score"] * x["weight"], -x.get("age_min", 999)),
        reverse=True
    )

    # ── Дедупликация по похожим заголовкам ───────────────────────
    unique, seen_titles = [], set()
    for a in articles:
        key = re.sub(r'[^a-zа-я0-9]', '', a["title"].lower())[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(a)

    return unique[:TOP_N]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GIST API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEADERS = lambda: {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github+json"}

def gist_read(gist_id, filename):
    try:
        r = requests.get(f"https://api.github.com/gists/{gist_id}", headers=HEADERS(), timeout=15)
        if r.status_code == 200:
            content = r.json()["files"].get(filename, {}).get("content", "")
            return json.loads(content) if content else {}
    except:
        pass
    return {}

def gist_write(gist_id, filename, data):
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=HEADERS(),
            json={"files": {filename: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}},
            timeout=15
        )
        return r.status_code == 200
    except:
        return False

def get_raw_url(gist_id, filename):
    """
    Возвращает прямой raw URL для чтения файла из Gist БЕЗ токена.
    Формат: https://gist.githubusercontent.com/USER/GIST_ID/raw/FILENAME
    Работает для secret gists — URL секретный, но авторизация не нужна.
    """
    try:
        r = requests.get(f"https://api.github.com/gists/{gist_id}", headers=HEADERS(), timeout=10)
        if r.status_code == 200:
            files = r.json().get("files", {})
            if filename in files:
                return files[filename].get("raw_url", "")
    except:
        pass
    # Fallback: собираем URL вручную
    return f"https://gist.githubusercontent.com/guzalmexmonova-ux/{gist_id}/raw/{filename}"

def get_or_create_gist():
    if GIST_ID:
        return GIST_ID
    # Ищем существующий
    try:
        r = requests.get("https://api.github.com/gists", headers=HEADERS(), timeout=10)
        if r.status_code == 200:
            for g in r.json():
                if g.get("description") == "agendalytica_data":
                    return g["id"]
    except:
        pass
    # Создаём новый (secret)
    try:
        r = requests.post(
            "https://api.github.com/gists",
            headers=HEADERS(),
            json={
                "description": "agendalytica_data",
                "public": False,   # SECRET gist — URL знает только ты
                "files": {
                    "queue.json":    {"content": json.dumps({"updated": "", "items": []})},
                    "analyzed.json": {"content": json.dumps({})},
                    "sent.json":     {"content": json.dumps({"hashes": []})},
                    "meta.json":     {"content": json.dumps({"raw_urls": {}})},
                }
            },
            timeout=15
        )
        if r.status_code == 201:
            gid = r.json()["id"]
            print(f"✅ Создан новый Gist: {gid}")
            print(f"   Добавь в Secrets: GIST_ID = {gid}")
            return gid
    except:
        pass
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    now_str = datetime.now(TZ).strftime('%d.%m.%Y %H:%M')
    print(f"🔄 Parser v4.0 — {now_str} TASHKENT")
    print(f"   Источников RSS: {len(RSS_FEEDS)} | GDELT срезов: {len(GDELT_FEEDS)}")

    gist_id = get_or_create_gist()
    if not gist_id:
        print("❌ Не удалось получить Gist ID. Добавь GIST_TOKEN в Secrets.")
        return

    # Получаем raw URL для queue.json (для Claude)
    raw_url = get_raw_url(gist_id, "queue.json")
    print(f"\n📎 RAW URL для Claude (сохрани один раз):")
    print(f"   {raw_url}\n")

    # Читаем уже отправленные
    sent = gist_read(gist_id, "sent.json")
    sent_hashes = set(sent.get("hashes", []))

    # Читаем очередь
    queue = gist_read(gist_id, "queue.json")
    queue_items = queue.get("items", [])
    queue_hashes = {a["hash"] for a in queue_items}

    # Парсим
    print("📡 Парсинг источников...")
    articles = fetch_all()
    print(f"✅ Найдено {len(articles)} статей (score ≥ {MIN_SCORE})")

    # Добавляем только новые
    added = 0
    for a in articles:
        if a["hash"] not in sent_hashes and a["hash"] not in queue_hashes:
            queue_items.append(a)
            added += 1

    # Сортируем и обрезаем
    queue_items.sort(key=lambda x: x["score"] * x["weight"], reverse=True)
    queue_items = queue_items[:100]

    # Записываем в Gist
    ok = gist_write(gist_id, "queue.json", {
        "updated": datetime.now(TZ).isoformat(),
        "raw_url": raw_url,
        "total":   len(queue_items),
        "items":   queue_items,
    })

    if ok:
        print(f"✅ Gist обновлён: +{added} новых, всего {len(queue_items)} в очереди")
        print(f"\n🏆 ТОП-5:")
        for i, a in enumerate(queue_items[:5], 1):
            age = f"T+{a['age_min']}мин" if a.get('age_min') else "GDELT"
            print(f"  [{i}] {a['score']}/10 | {age} | [{a['source']}] {a['title'][:80]}")
        print(f"\n📎 Для Claude — читать queue.json:")
        print(f"   {raw_url}")
else:
        print("❌ Ошибка записи в Gist")
    with open("news_queue.json", "w", encoding="utf-8") as f:
        json.dump({"updated": ...}, f, ensure_ascii=False, indent=2)
    print(f"✅ news_queue.json сохранён...")

if __name__ == "__main__":
    main()
