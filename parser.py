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

HOURS_WINDOW  = 4        # окно свежести в часах (4ч = нет слепых зон между 3 сессиями)
MIN_SCORE     = 5        # минимальный балл (из 10) — пограничный свежак проходит, мусор в 0
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

# Жёсткий вето-фильтр: спорт/быт прорывается с высоким баллом из-за слова "war"
VETO_PATTERNS = [
    " vs ", " vs.", "overtime", "stabbing", "pleads guilty", "win prize",
    "awards", "box office", "red carpet", "world cup call", "draft pick",
    "transfer fee", "bauer sucht", "sucht frau", "tv-show", "tv show",
    "reality show", "knicks", "lakers", "cavs", "neymar",
]

def _has(kw: str, text: str) -> bool:
    """Совпадение по ГРАНИЦЕ слова: 'war' не сработает в 'warrior'/'award'/'forward'."""
    # для фраз с пробелом — обычное вхождение; для слов — граница \b
    if " " in kw:
        return kw in text
    return re.search(r"(?<![a-zа-яё0-9])" + re.escape(kw) + r"(?![a-zа-яё0-9])", text) is not None


def score_article(title: str, summary: str = "", domain: str = "") -> int:
    """
    Скоринг Вариант C: счёт совпадений + штраф за одно случайное слово.
    GDELT и не-Tier1 режутся. Поиск по границам слова. Разброс 0-10.
    """
    tl = (title + " " + summary).lower()
    title_lower = title.lower()

    # ── Вето: спорт / быт / шоу-бизнес → сразу 0 ──────────────
    for v in VETO_PATTERNS:
        if v in tl:
            return 0
    for p in NOISE_PATTERNS:
        if p in tl:
            return 0
    if domain in NOISE_DOMAINS:
        return 0
    for am in ANALYTICAL_MARKERS:
        if am in title_lower:
            return 0

    # ── Базовый балл + СЧЁТ совпадений (по границам слова) ──────
    base = 0
    total_hits = 0           # сколько вообще ключей сработало
    strong_hits = 0          # сколько сильных (балл ≥ 8) сработало
    for pts, kw_list in SCORES_MAP.items():
        for kw in kw_list:
            if _has(kw, tl):
                base = max(base, pts)
                total_hits += 1
                if pts >= 8:
                    strong_hits += 1

    if base == 0:
        return 0

    is_gdelt = domain.startswith("GDELT/")        # только GDELT-срезы
    is_tier1 = domain in TIER1_DOMAINS

    score = base

    # ── ШТРАФЫ НЕ СУММИРУЮТСЯ: берём ОДИН максимальный −2 ──────
    # Иначе реальный свежак (одно сильное слово + GDELT) терял сразу 4 балла.
    penalty = 0
    if total_hits == 1 and not is_tier1:
        penalty = 2                       # зацепился одним словом
    if is_gdelt:
        penalty = max(penalty, 2)         # GDELT (не суммируем с предыдущим)
    # мягкий пол 4: мусор без ключей уже отсечён вето/base==0,
    # а реальная новость с одним словом получит 4-5 и может пройти
    score = max(4, score - penalty) if penalty else score

    # ── Бонус за плотность сигналов (несколько сильных ключей) ──
    if strong_hits >= 2:
        score = min(10, score + 1)

    # ── Breaking marker → +1 ──
    for bm in BREAKING_MARKERS:
        if _has(bm, tl):
            score = min(10, score + 1)
            break

    # ── Anchor keyword → +1 ──
    for ak in ANCHOR_KEYWORDS:
        if _has(ak, tl):
            score = min(10, score + 1)
            break

    # ── Tier-1 домен бонус УБРАН: домен не должен задирать пустую новость ──
    # (FT-проходняк больше не лезет в 10/10 только из-за домена)

    return max(0, min(10, score))


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
                # GDELT отдаёт pubDate — берём реальный возраст
                pub = e.get("published_parsed") or e.get("updated_parsed")
                age_min = None
                ts_utc = datetime.now(timezone.utc)
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                    age_min = round((datetime.now(timezone.utc) - pub_dt).total_seconds() / 60, 1)
                    ts_utc = pub_dt
                seen_hashes.add(h)
                gdelt_ok += 1
                articles.append({
                    "hash": h, "title": title, "summary": "",
                    "link": link, "source": source_name,
                    "score": sc, "weight": weight, "status": "new",
                    "ts": datetime.now(TZ).isoformat(),
                    "age_min": age_min,   # реальный возраст или None
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

    # ── Дедупликация по смыслу (один сюжет от разных доменов) ────
    import unicodedata
    STOP = {"the","a","an","of","in","on","to","for","and","is","as","at","по","в","на","и",
            "о","с","за","из","что","как","says","said","after","amid","over","with"}
    def sig(title):
        t = unicodedata.normalize("NFKD", title.lower())
        words = re.findall(r"[a-zа-я0-9]+", t)
        words = [w for w in words if w not in STOP and len(w) > 2]
        return frozenset(words[:8])   # ключевые сущности заголовка

    unique, seen_sigs = [], []
    for a in articles:
        s = sig(a["title"])
        dup = False
        for prev in seen_sigs:
            # пересечение ≥60% ключевых слов = тот же сюжет
            if s and prev and len(s & prev) / max(len(s), 1) >= 0.6:
                dup = True
                break
        if not dup:
            seen_sigs.append(s)
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
    print(f"🔄 Parser v5.0 — {now_str} TASHKENT")
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

    # Добавляем только новые + копим список того что отправим СЕЙЧАС
    added = 0
    fresh_to_send = []          # только реально новые статьи для этой отправки
    for a in articles:
        if a["hash"] not in sent_hashes and a["hash"] not in queue_hashes:
            queue_items.append(a)
            fresh_to_send.append(a)
            added += 1

    # Фильтруем: оставляем только статьи за последние 4 часа (нет слепых зон)
    cutoff_queue = datetime.now(TZ) - timedelta(hours=4)
    queue_items = [
        a for a in queue_items
        if datetime.fromisoformat(a["ts"]) >= cutoff_queue
    ]
    # Сортируем по свежести + баллу
    queue_items.sort(key=lambda x: (x["score"] * x["weight"], x["ts"]), reverse=True)
    queue_items = queue_items[:50]

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

    # ── Сохраняем свежую очередь (4ч) ──────────────────────
    with open("news_queue.json", "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(TZ).isoformat(), "items": queue_items}, f, ensure_ascii=False, indent=2)
    print(f"✅ news_queue.json сохранён ({len(queue_items)} статей)")

    # ── Обновляем лучшие за день (не удаляем старые) ────────
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    from pathlib import Path
    daily_file = Path("daily_best.json")
    daily = json.loads(daily_file.read_text(encoding="utf-8")) if daily_file.exists() else {"date": today, "items": []}

    # Сбрасываем если новый день
    if daily.get("date") != today:
        daily = {"date": today, "items": []}

    # Добавляем только новые статьи
    daily_hashes = {a["hash"] for a in daily["items"]}
    for a in queue_items:
        if a["hash"] not in daily_hashes:
            daily["items"].append(a)

    # Топ-20 за день по баллу
    daily["items"].sort(key=lambda x: x["score"] * x["weight"], reverse=True)
    daily["items"] = daily["items"][:20]
    daily["updated"] = datetime.now(TZ).isoformat()

    daily_file.write_text(json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ daily_best.json обновлён ({len(daily['items'])} лучших за {today})")

    # ── Обновляем sent.json: помечаем отправленное, чистим >24ч ──
    now_iso = datetime.now(TZ).isoformat()
    sent_records = sent.get("records", [])
    # старый формат (только hashes) — мигрируем
    existing = {r["h"] for r in sent_records}
    for a in fresh_to_send:
        if a["hash"] not in existing:
            sent_records.append({"h": a["hash"], "ts": now_iso})
    cutoff_sent = datetime.now(TZ) - timedelta(hours=24)
    sent_records = [
        r for r in sent_records
        if datetime.fromisoformat(r["ts"]) >= cutoff_sent
    ]
    # ── Флаг саммари: ПЕРВЫЙ запуск после 18:30 TSH за день ──
    # Надёжно: не зависит от точной минуты запуска (cron-job.org плавает).
    # Запоминаем дату последнего саммари в sent.json.
    now_tsh = datetime.now(TZ)
    last_summary_date = sent.get("last_summary_date", "")
    is_summary = (
        (now_tsh.hour > 18 or (now_tsh.hour == 18 and now_tsh.minute >= 30))
        and now_tsh.hour < 24
        and last_summary_date != today
    )

    gist_payload = {
        "hashes": [r["h"] for r in sent_records],
        "records": sent_records,
        "last_summary_date": today if is_summary else last_summary_date,
    }
    gist_write(gist_id, "sent.json", gist_payload)
    print(f"💾 sent.json: {len(sent_records)} хэшей (24ч) | саммари сегодня: {'да' if is_summary else 'нет'}")

    # ── Отправка: только НОВОЕ; раз в день после 18:30 — саммари ──
    send_to_telegram(fresh_to_send, daily["items"], today, is_summary)


def send_to_telegram(fresh_items: list, daily_items: list, today: str, is_summary: bool = False):
    """Шлёт только новые статьи. В 18:30 — добавляет саммари дня."""
    token   = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("⚠ TELEGRAM_TOKEN/CHAT_ID не заданы — пропуск")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    now_str = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    def tg_send(text: str):
        try:
            r = requests.post(url, json={
                "chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }, timeout=15)
            return r.status_code == 200
        except Exception as e:
            print(f"  ⚠ TG error: {e}")
            return False

    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    def fmt_age(a):
        am = a.get("age_min")
        if am is None:
            return "GDELT"
        return f"T+{am}м"

    # ── Только новые статьи ──────────────────────────────────
    if fresh_items:
        header = (
            f"🔄 <b>СВЕЖЕЕ — {now_str} TSH</b>\n"
            f"📦 Новых статей: {len(fresh_items)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        lines = []
        for i, a in enumerate(fresh_items, 1):
            lines.append(
                f"<b>[{i}] {a['score']}/10</b> | {fmt_age(a)} | {a['source']}\n"
                f"📰 {a['title'][:120]}\n"
                f"👉 <a href='{a['link']}'>Читать ({a['source']})</a>\n"
            )
        for idx, batch in enumerate(chunks(lines, 10)):
            prefix = header if idx == 0 else f"<b>СВЕЖЕЕ (продолжение {idx+1})</b>\n\n"
            msg = prefix + "\n".join(batch)
            if len(msg) > 4000:
                msg = msg[:4000] + "..."
            ok = tg_send(msg)
            print(f"  📤 СВЕЖЕЕ часть {idx+1}: {'✅' if ok else '❌'}")
    else:
        print("  ✓ Новых статей нет — отправка пропущена")

    # ── Саммари дня (только в 18:30) ─────────────────────────
    if is_summary and daily_items:
        top1 = daily_items[0]
        header2 = (
            f"⭐ <b>САММАРИ ДНЯ — {today}</b>\n"
            f"🏆 Главное за день: {top1['title'][:90]}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        lines2 = []
        for i, a in enumerate(daily_items, 1):
            lines2.append(
                f"<b>[{i}] {a['score']}/10</b> | {a['source']}\n"
                f"📰 {a['title'][:120]}\n"
                f"👉 <a href='{a['link']}'>Читать ({a['source']})</a>\n"
            )
        for idx, batch in enumerate(chunks(lines2, 10)):
            prefix = header2 if idx == 0 else f"<b>САММАРИ (продолжение {idx+1})</b>\n\n"
            msg = prefix + "\n".join(batch)
            if len(msg) > 4000:
                msg = msg[:4000] + "..."
            ok = tg_send(msg)
            print(f"  📤 САММАРИ часть {idx+1}: {'✅' if ok else '❌'}")

    print("✅ Telegram отправка завершена")


if __name__ == "__main__":
    main()
