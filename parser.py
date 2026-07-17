#!/usr/bin/env python3
"""
AGENDALYTICA — PARSER v6.0 (LIGHT)
Задача: найти НОВУЮ новость → первоисточник, дата, переведённый заголовок, ссылка.
Полный текст статей больше не качается — это и давало 11 минут и таймауты.
Убраны: newspaper4k, BeautifulSoup, httpx, nltk. Нужны только feedparser + requests.
"""

import os
import sys
import re
import json
import hashlib
import traceback
from datetime import datetime, timezone, timedelta

import feedparser
import requests

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  КОНФИГ И КРИТИЧЕСКАЯ ВАЛИДАЦИЯ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Скользящее окно: берём период от прошлого запуска до сейчас, а не жёсткие N часов.
# Если GitHub пропустил запуск (а он пропускает) — окно само растянется, ничего не потеряем.
OVERLAP_MIN = 30        # нахлёст 30 мин: фиды с задержкой успевают, дедуп режет повторы
MIN_WINDOW_H = 2        # минимум окна 2ч: больше статей на запуск
MAX_WINDOW_H = 6        # потолок, чтобы после долгого простоя не тянуть сутки
HOURS_WINDOW = 2        # запасное значение, если нет данных о прошлом запуске
MIN_SCORE = 3           # минимальный балл 3: пропускаем больше средних новостей
MIN_SCORE_UNDATED = 6   # без даты: было 7, теперь 6
TOP_N = 80              # топ статей в очереди
ENRICH_LIMIT = 30       # сколько заголовков переводить за запуск
MAX_PER_SOURCE = 3      # не больше N новостей от одного издания за пачку
MAX_PER_TOPIC = 5       # не больше N новостей на одну ГОРЯЧУЮ тему (война/выборы)

TZ = timezone(timedelta(hours=5))  # Ташкент GMT+5

DEDUP_HOURS = 24        # память сюжетов: одна история = одна отправка за сутки
SIM_THRESHOLD = 0.45    # порог схожести заголовков

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ИСТОЧНИКИ ДАННЫХ (без изменений)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GDELT_FEEDS = [
    # 12 узких запросов душились по 429 (GitHub Actions сидит на общих IP).
    # 4 широких по 250 записей = меньше стуков, больше данных.
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(war+OR+conflict+OR+invasion+OR+airstrike+OR+missile+OR+nuclear+OR+escalation+OR+coup+OR+mobilization+OR+ceasefire+OR+sanctions+OR+assassination)&mode=artlist&maxrecords=100&format=rss&timespan=4h", "GDELT/GEOPOLITICS", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Ukraine+OR+Russia+OR+Israel+OR+Gaza+OR+Iran+OR+Houthi+OR+Hezbollah+OR+Putin+OR+Zelensky)&mode=artlist&maxrecords=100&format=rss&timespan=4h", "GDELT/HOTSPOTS", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Federal+Reserve+OR+ECB+OR+rate+hike+OR+rate+cut+OR+recession+OR+inflation+OR+default+OR+market+crash+OR+brent+OR+OPEC+OR+gold)&mode=artlist&maxrecords=100&format=rss&timespan=4h", "GDELT/MARKETS", 4),
    ("https://api.gdeltproject.org/api/v2/doc/doc?query=(Taiwan+OR+South+China+Sea+OR+semiconductor+OR+TSMC+OR+chip+ban+OR+Uzbekistan+OR+Kazakhstan+OR+SCO+OR+CSTO+OR+cyberattack)&mode=artlist&maxrecords=100&format=rss&timespan=4h", "GDELT/ASIA_TECH", 4),
]

RSS_FEEDS = [
    # ═══ ЖИВОЕ И СВЕЖЕЕ (проверено диагностикой 17.07.2026) ═══
    # Telegram-мост: самый быстрый канал (TG/Bloomberg дал 10м).
    # Оставлены только ключевые — хост режет по 429 при частых запросах.
    {"url": "https://tg.i-c-a.su/rss/bbbreaking", "source": "TG/Bloomberg", "weight": 4},
    {"url": "https://tg.i-c-a.su/rss/market_twits", "source": "TG/Markets", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rian_ru", "source": "TG/RIA", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/interfaxonline", "source": "TG/Interfax", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/centralasian", "source": "TG/CentralAsia", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/war_monitor", "source": "TG/WarMonitor", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/rybar", "source": "TG/Rybar", "weight": 3},
    {"url": "https://tg.i-c-a.su/rss/macronomics", "source": "TG/Macro", "weight": 3},

    # Издания напрямую — живые, свежие
    {"url": "https://tass.ru/rss/v2.xml", "source": "TASS", "weight": 2},                       # 17м
    {"url": "https://lenta.ru/rss/news", "source": "Lenta.ru", "weight": 2},                    # 39м
    {"url": "https://www.ft.com/world?format=rss", "source": "FT", "weight": 4},                # 83м
    {"url": "https://feeds.bloomberg.com/markets/news.rss", "source": "Bloomberg", "weight": 4},# 180м
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "source": "Al Jazeera", "weight": 3},  # 271м
    {"url": "https://www.scmp.com/rss/91/feed", "source": "SCMP", "weight": 3},                 # 201м
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "source": "BBC World", "weight": 4}, # 720м
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "source": "NYT World", "weight": 3},
    {"url": "https://thediplomat.com/feed", "source": "The Diplomat", "weight": 3},
    {"url": "https://asia.nikkei.com/rss/feed/nar", "source": "Nikkei Asia", "weight": 3},
    {"url": "https://www.crisisgroup.org/rss/139", "source": "Crisis Group", "weight": 3},
    {"url": "https://www.foreignaffairs.com/rss.xml", "source": "Foreign Affairs", "weight": 3},

    # Официальные — редко публикуют, но это первоисточник без задержки
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "source": "FED", "weight": 5},
    {"url": "https://www.ecb.europa.eu/rss/press.html", "source": "ECB", "weight": 5},
    {"url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml", "source": "UN", "weight": 4},

    # Google News — агрегатор, но поисковые фиды дают свежее (43-91м)
    {"url": "https://news.google.com/rss/search?q=Federal+Reserve+OR+ECB+OR+BOE+rate+decision+when:6h&hl=en-US", "source": "GNews/CentralBanks", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=brent+crude+oil+OPEC+cut+OR+crash+when:6h&hl=en-US", "source": "GNews/Oil", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=gold+XAU+price+surge+OR+fall+when:6h&hl=en-US", "source": "GNews/Gold", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=breaking+war+attack+crisis+when:6h&hl=en-US", "source": "GNews/Breaking", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=TSMC+ASML+Nvidia+chip+ban+export+when:6h&hl=en-US", "source": "GNews/Chips", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Israel+Iran+Gaza+Houthi+when:6h&hl=en-US", "source": "GNews/Mideast", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=USA+China+Taiwan+military+Strait+when:6h&hl=en-US", "source": "GNews/USA-China", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=война+санкции+мобилизация+НАТО+when:6h&hl=ru&gl=RU&ceid=RU:ru", "source": "GNews/RU-Geo", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=ФРС+ставка+рецессия+инфляция+нефть+when:6h&hl=ru&gl=RU&ceid=RU:ru", "source": "GNews/RU-Macro", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Узбекистан+Казахстан+Мирзиёев+Токаев+when:6h&hl=ru&gl=UZ&ceid=UZ:ru", "source": "GNews/RU-CA", "weight": 3},
    {"url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "source": "GNews/Home-US", "weight": 4},
    {"url": "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE?hl=en-US&gl=US&ceid=US:en", "source": "GNews/World-US", "weight": 4},
    {"url": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en", "source": "GNews/Business-US", "weight": 4},

    # Nitter — большинство зеркал протухло (Trump/X отдавал 4-месячную давность).
    # Оставлены только те, где диагностика показала свежесть.
    {"url": "https://nitter.net/WhiteHouse/rss", "source": "WhiteHouse/X", "weight": 5},        # 200м
    {"url": "https://nitter.net/POTUS/rss", "source": "POTUS/X", "weight": 5},                  # 945м
    {"url": "https://nitter.net/ZelenskyyUa/rss", "source": "Zelensky/X", "weight": 4},
    {"url": "https://nitter.net/elonmusk/rss", "source": "Musk/X", "weight": 3},


    # ═══ ВОЗВРАЩЁННЫЕ АВТОРИТЕТНЫЕ (проверено candidates.py 17.07.2026) ═══
    # Reuters и AP закрыли прямой RSS — берём через поиск Google News.
    # Издатель вытаскивается из хвоста заголовка, в ленте видно "Reuters", а не "GNews".
    {"url": "https://news.google.com/rss/search?q=site:reuters.com+when:6h&hl=en-US&gl=US&ceid=US:en", "source": "Reuters", "weight": 5},
    {"url": "https://news.google.com/rss/search?q=site:apnews.com+when:6h&hl=en-US&gl=US&ceid=US:en", "source": "AP", "weight": 5},
    {"url": "https://news.google.com/rss/search?q=site:afp.com+OR+site:barrons.com/afp+when:12h&hl=en-US", "source": "AFP", "weight": 4},

    # Bloomberg — прямые фиды живые
    {"url": "https://feeds.bloomberg.com/politics/news.rss", "source": "Bloomberg Politics", "weight": 4},
    {"url": "https://feeds.bloomberg.com/technology/news.rss", "source": "Bloomberg Tech", "weight": 3},

    # WSJ — рабочий URL (старый feeds.a.dj.com отдавал 1.5-летнее старьё)
    {"url": "https://feeds.content.dowjones.io/public/rss/RSSWorldNews", "source": "WSJ", "weight": 4},

    # Свежие издания (10-16 мин на проверке)
    {"url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "source": "CNBC World", "weight": 3},
    {"url": "https://www.france24.com/en/rss", "source": "France24", "weight": 3},
    {"url": "https://feeds.npr.org/1004/rss.xml", "source": "NPR World", "weight": 3},
    {"url": "https://www.theguardian.com/world/rss", "source": "Guardian", "weight": 3},
    {"url": "https://rss.dw.com/rdf/rss-en-world", "source": "DW", "weight": 3},

    # Ближний Восток / Центральная Азия
    {"url": "https://www.al-monitor.com/rss", "source": "Al-Monitor", "weight": 4},
    {"url": "https://news.google.com/rss/search?q=site:eurasianet.org+when:24h&hl=en-US", "source": "EurasiaNet", "weight": 3},

    # Закулисье Вашингтона и Брюсселя
    {"url": "https://rss.politico.com/politics-news.xml", "source": "Politico US", "weight": 4},
    {"url": "https://rss.politico.com/congress.xml", "source": "Politico Congress", "weight": 3},
    {"url": "https://www.politico.eu/feed/", "source": "Politico EU", "weight": 3},
    {"url": "https://api.axios.com/feed/", "source": "Axios", "weight": 4},

    # Аналитика
    {"url": "https://geopoliticalfutures.com/feed/", "source": "Geopolitical Futures", "weight": 3},
    {"url": "https://foreignpolicy.com/feed/", "source": "Foreign Policy", "weight": 3},

    # Официальные — редко, но первоисточник
    {"url": "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=1&Site=945&max=20", "source": "Pentagon", "weight": 5},
    {"url": "https://ec.europa.eu/commission/presscorner/api/rss?language=en&pagesize=20", "source": "EU Commission", "weight": 4},
    {"url": "https://www.iaea.org/feeds/topnews", "source": "IAEA", "weight": 5},
    {"url": "https://www.eia.gov/rss/todayinenergy.xml", "source": "EIA", "weight": 4},
    {"url": "https://www.bankofengland.co.uk/rss/news", "source": "BoE", "weight": 4},


    # ═══ АУДИТОРИЯ КАНАЛА: CA / PH / AU / UK / US (проверено 17.07.2026) ═══
    # Канада
    {"url": "https://rss.cbc.ca/lineup/politics.xml", "source": "CBC Politics", "weight": 4},
    {"url": "https://rss.cbc.ca/lineup/world.xml", "source": "CBC World", "weight": 4},
    {"url": "https://news.google.com/rss/search?q=site:theglobeandmail.com+when:6h&hl=en-CA&gl=CA&ceid=CA:en", "source": "Globe & Mail", "weight": 4},
    {"url": "https://news.google.com/rss/search?q=site:nationalpost.com+when:6h&hl=en-CA&gl=CA&ceid=CA:en", "source": "National Post", "weight": 3},

    # Филиппины
    {"url": "https://www.rappler.com/feed/", "source": "Rappler", "weight": 4},
    {"url": "https://news.google.com/rss/search?q=site:philstar.com+when:6h&hl=en-PH&gl=PH&ceid=PH:en", "source": "Philippine Star", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=site:news.abs-cbn.com+when:6h&hl=en-PH&gl=PH&ceid=PH:en", "source": "ABS-CBN", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=Philippines+South+China+Sea+OR+West+Philippine+Sea+when:12h&hl=en-PH&gl=PH&ceid=PH:en", "source": "PH South China Sea", "weight": 4},

    # Австралия
    {"url": "https://www.abc.net.au/news/feed/2942460/rss.xml", "source": "ABC News AU", "weight": 4},
    {"url": "https://www.abc.net.au/news/feed/51120/rss.xml", "source": "ABC AU Politics", "weight": 3},
    {"url": "https://www.smh.com.au/rss/world.xml", "source": "Sydney Morning Herald", "weight": 3},
    {"url": "https://www.smh.com.au/rss/politics/federal.xml", "source": "SMH Politics", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=site:theage.com.au+when:6h&hl=en-AU&gl=AU&ceid=AU:en", "source": "The Age", "weight": 3},

    # Великобритания — усиление
    {"url": "https://feeds.skynews.com/feeds/rss/uk.xml", "source": "Sky News UK", "weight": 4},
    {"url": "https://feeds.skynews.com/feeds/rss/politics.xml", "source": "Sky News Politics", "weight": 3},
    {"url": "https://news.google.com/rss/search?q=site:telegraph.co.uk+when:6h&hl=en-GB&gl=GB&ceid=GB:en", "source": "Telegraph", "weight": 3},
    {"url": "https://feeds.bbci.co.uk/news/politics/rss.xml", "source": "BBC Politics", "weight": 4},

    # США — Конгресс
    {"url": "https://thehill.com/rss/syndicator/19110", "source": "The Hill", "weight": 4},
    {"url": "https://rollcall.com/feed/", "source": "Roll Call", "weight": 3},

    # ═══ НЕ ПРОШЛИ ПРОВЕРКУ (403/404) ═══
    # Stratfor, Chatham House, RUSI, CSIS, ISW, Carnegie — блокируют ботов
    # OFAC, Treasury, White House, State Dept, NATO, IMF, BIS, OPEC, World Bank — 403/404
    # Kyiv Independent, Times of Israel, Eurasianet direct — 403/404

    # ═══ УДАЛЕНО ПО ИТОГАМ ДИАГНОСТИКИ ═══
    # 404/403/401 — фиды закрыты или сменили URL:
    #   Reuters, Reuters World (Reuters закрыл RSS), AP News, BIS, NATO, Pentagon,
    #   IMF, IEA, WTO (битый XML), ZeroHedge, EurasiaNet, AOL x2,
    #   Trump/Truth x2 (403), TG/Reuters (403),
    #   nitter: Pentagon, IsraelMFA, TurkeyMFA, UzbMFA (404)
    # Протухшие зеркала (отдают старьё):
    #   WSJ (~1.5 года), Kremlin/X (~4 года), ChinaSpox/X (~1.5 года),
    #   Trump/X (~4 мес), Yahoo/Finance (~48 дней), CNBC (~17 дней)
    # Yahoo/AOL: yahoo.com в NOISE_DOMAINS — фиды всё равно отсеивались
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СКОРИНГ И КЛЮЧЕВЫЕ СЛОВА (без изменений)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCORE_10 = ["nuclear", "ядерн", "nato article 5", "invasion", "вторжение", "assassination", "покушение", "collapse", "коллапс"]
SCORE_9 = ["war", "война", "coup", "переворот", "hypersonic", "гиперзвук", "martial law", "военное положение", "impeached", "импичмент", "default", "дефолт", "market crash", "обвал рынка", "oil crash", "нефть упала", "tsmc ban", "iran nuclear", "иран ядерн"]
SCORE_8 = ["air strike", "air strikes", "airstrikes", "missile strike", "military strike",
    "strikes on", "strikes against", "strikes key", "strikes near", "retaliatory strike",
    "us strikes", "israeli strikes", "launches strikes", "наносит удар", "нанесли удар", "наносят удар", "нанес удар", "нанёс удар", "нанесла удар",
    "ракетный удар", "авиаудар", "shelling", "обстрел", "bombardment", "attack", "атак", "escalation", "эскалац", "ballistic", "баллистическ", "airstrike", "авиаудар", "drone strike", "удар дрона", "mobilization", "мобилизац", "mutiny", "мятеж", "resigns", "отставк", "resignation", "step down", "scandal", "скандал", "rate hike", "rate cut", "повышение ставки", "снижение ставки", "recession", "рецессия", "gold surges", "золото выросло", "xauusd", "opec cut", "опек сокращ", "chip ban", "export ban", "запрет экспорта", "cyberattack", "кибератак", "cyber warfare", "кибервойна", "sovereign debt", "госдолг", "bond yields", "доходность облигаций", "powell", "пауэлл", "warsh", "уорш", "lagarde", "лагард", "bank run"]
SCORE_7 = ["missile", "ракета", "ceasefire", "перемирие", "blockade", "блокада", "strait", "пролив", "uranium", "уран", "lng", "спг", "rare earth", "редкоземельн", "copper", "медь", "lithium", "литий", "trade war", "торговая война", "tariff", "пошлин", "middle corridor", "срединный коридор", "gold hits", "gold falls", "brent falls", "xau", "inflation surge", "инфляция выросла", "fed decision"]
SCORE_6 = [
    # ═ Аудитория канала: события в этих странах повышаем в приоритете ═
    # США
    "biden", "trump", "harris", "vance", "rubio", "musk", "byron", "senate", "congress",
    "supreme court", "верховный суд", "белый дом", "конгресс", "сенат",
    # Великобритания
    "downing street", "starmer", "burnham", "farage", "sunak", "westminster",
    "даунинг-стрит", "стармер", "фараж", "вестминстер", "ботанический сад",
    # Канада
    "carney", "poilievre", "trudeau", "ottawa", "оттава", "карни", "трюдо",
    # Филиппины
    "marcos", "duterte", "manila", "philippines", "west philippine sea",
    "маркос", "манила", "филиппин", "западно-филиппинск",
    # Австралия
    "albanese", "dutton", "canberra", "aukus", "аукус", "альбаниз", "канберра",
    # общие политические
    "summit", "саммит", "talks", "переговор", "agreement", "соглашение",
    "president", "президент", "minister", "министр", "chancellor", "канцлер",
    "election", "выборы", "vote", "голосование", "protest", "протест",
    "border", "граница", "treaty", "договор", "alliance", "альянс",
    "military aid", "военная помощь", "weapons", "оружие", "troops", "войска",
    "central bank", "центробанк", "gdp", "ввп", "budget", "бюджет",
    "sanctions", "санкци", "conflict", "конфликт", "embargo", "эмбарго", "froze assets", "заморозил активы", "brics summit", "саммит брикс", "trump signs", "трамп подписал", "trump announces", "трамп объявил", "trump orders", "трамп ввёл", "putin orders", "путин приказал", "putin signs", "путин подписал", "xi jinping warns", "си цзиньпин", "mirziyoyev", "мирзиёев", "tokayev", "токаев", "csto", "одкб", "sco", "шос", "expelled ambassador", "отозвал посла", "cut diplomatic ties", "разорвал дипотношения", "issued ultimatum", "выдвинул ультиматум", "signed treaty", "подписал договор", "imposed sanctions", "ввёл санкции", "merz", "мерц", "opec+", "опек+", "seized assets", "изъял активы", "parliament voted", "конгресс проголосовал", "дума приняла", "no-confidence vote", "вотум недоверия", "cabinet reshuffle", "перестановки в правительстве"]

SCORES_MAP = {10: SCORE_10, 9: SCORE_9, 8: SCORE_8, 7: SCORE_7, 6: SCORE_6}
BREAKING_MARKERS = ["breaking", "just in", "confirmed", "urgent", "alert", "flash", "exclusive", "срочно", "только что", "сейчас", "экстренно", "подтверждено", "молния", "флэш"]
ANCHOR_KEYWORDS = ["nuclear", "ядерн", "nato article 5", "invasion", "вторжение", "assassination", "покушение", "war", "война", "coup", "переворот", "hypersonic", "гиперзвук", "martial law", "военное положение", "default", "дефолт", "market crash", "oil crash", "airstrike", "авиаудар", "mobilization", "мобилизац", "rate hike", "rate cut", "collapse", "коллапс", "trump signs", "трамп подписал", "trump orders", "putin orders", "путин приказал", "powell", "пауэлл", "lagarde", "лагард", "brent falls", "gold surges"]
TIER1_SOURCES = {"reuters", "ap", "afp", "bloomberg", "bloomberg politics", "bloomberg tech",
    "cbc politics", "cbc world", "globe & mail", "rappler", "abs-cbn",
    "abc news au", "sydney morning herald", "sky news uk", "bbc politics", "the hill",
    "wsj", "ft", "pentagon", "iaea", "eia", "boe", "eu commission", "axios",
    "politico us", "politico eu", "politico congress", "al-monitor", "guardian",
    "france24", "npr world", "dw", "the new york times", "the economist"}
TIER1_DOMAINS = {"reuters.com", "bloomberg.com", "ft.com", "wsj.com", "apnews.com", "federalreserve.gov", "imf.org", "bis.org", "ecb.europa.eu", "nato.int", "defense.gov", "un.org", "iea.org", "wto.org", "nytimes.com", "bbc.com", "bbc.co.uk", "truthsocial.com"}
NOISE_DOMAINS = {"msn.com", "buzzfeed.com", "huffpost.com", "dailymail.co.uk", "fxstreet.com", "fxempire.com", "investopedia.com", "seekingalpha.com", "yahoo.com", "tmz.com", "espn.com", "bleacherreport.com", "kp.ru", "mk.ru", "spletnik.ru", "sports.ru", "championat.com", "starhit.ru", "varindia.com", "asiaone.com", "eturbonews.com", "benzinga.com", "ndtv.com", "entertainmentweekly.com", "people.com", "cosmopolitan.com", "vogue.com"}
NOISE_PATTERNS = ["whiskey", "виски", "coffee", "кофе", "barista", "restaurant", "ресторан", "recipe", "рецепт", "food", "beer", "пиво", "wine", "вино", "chef", "vacation", "отпуск", "tourism", "hotel", "resort", "курорт", "soccer", "football goal", "basketball", "баскетбол", "nba draft", "nfl draft", "transfer fee", "трансфер игрок", "celebrity", "знаменитость", "hollywood", "box office", "music video", "grammy", "oscar", "emmy", "album release", "red carpet", "seo tips", "digital marketing", "influencer", "инфлюенсер", "smartphone launch", "smartwatch", "gaming laptop", "diet tips", "weight loss", "похудение", "yoga", "meditation", "horoscope", "гороскоп", "zodiac", "week in review", "monthly roundup", "annual report", "year in review", "everything you need to know", "deep dive into", "a brief history", "итоги недели", "годовой отчёт", "история вопроса", "всё что нужно знать", "on our radar", "prioritising peace", "prioritizing peace", "how to ", "guide to", "what is ", "explainer:", "explained:", "opinion:", "мнение:", "колонка:", "the case for", "the case against"]
ANALYTICAL_MARKERS = ["week in review", "monthly roundup", "annual report", "year in review", "everything you need to know", "deep dive into", "a brief history", "итоги недели", "годовой отчёт", "история вопроса", "on our radar"]
# Локальный шум: "rate hike" от коммуналки Огайо проходил как 7/10
# Не новости, а болтовня: "Речь на вручении дипломов", "Назад к основам в ООН"
# Погода и природа: "thunderstorms strike across Europe" ловилось как военный удар
WEATHER_NOISE = [
    "weather tracker", "thunderstorm", "heatwave", "heat wave", "rainfall",
    "forecast: rain", "snowfall", "hurricane season", "погода", "гроз", "жара",
]

FORMAT_NOISE = [
    "commencement", "graduation", "diploma", "ceremony", "церемони",
    "speech at", "remarks at", "keynote", "выступление на", "речь на",
    "podcast", "подкаст", "webinar", "вебинар", "back to basics",
    "in conversation with", "q&a with", "interview with", "интервью с",
    "our podcast", "episode", "эпизод", "watch:", "listen:",
]

LOCAL_NOISE = [
    "aes ohio", "utility rate", "utility bill", "electric bill", "water rate",
    "city council", "county board", "school board", "local residents",
    # Спорт: раньше "финал ЧМ", гольф, "бегуны и гонщики" проходили через election/strike
    "world cup", "чм-", "чемпионат мира", "финал ", "мессия", "messi",
    "golf", "гольф", "singapore open", "olympic", "олимпи",
    "runners and riders", "бегуны и гонщики", "flowerhorn", "гибридные рыбы",
    # Развлечения, гейминг, колонки
    "god of war", "кратос", "digested week", "diminished by",
    "прощай", "рецензия", "review of", "how he drinks", "как он пьет",
    "netflix", "нетфликс", "hbo", "amazon prime",
    # Локальная бюрократия РФ (проходит через "president", "минист")
    "госдолг", "ратифицировал", "госдума приняла в третьем",
    "хайнань", "брянск", "абхаз", "россельхознадзор",
    "обновлённые учебники", "ран заявил", "рао ", "минкультуры",
    "rupee", "rupees", "₹", "per 10 gram", "per kg", "rs 3", "rs 7", "/10 gram", "/kg",
    "lakh", "crore", "sensex", "nifty",
    "labor strike", "labour strike", "workers strike", "hunger strike", "забастовк",
]

VETO_PATTERNS = [" vs ", " vs.", "overtime", "stabbing", "pleads guilty", "win prize", "awards", "box office", "red carpet", "world cup call", "draft pick", "transfer fee", "bauer sucht", "sucht frau", "tv-show", "tv show", "reality show", "knicks", "lakers", "cavs", "neymar"]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import time as _time
from urllib.parse import urlparse

# Троттлинг по хостам: GDELT и tg.i-c-a.su жёстко режут частые запросы (429).
# Без этого парсер терял 9 из 12 GDELT и 24 из 25 TG на КАЖДОМ запуске.
HOST_DELAY = {
    "api.gdeltproject.org": 20.0,
    "tg.i-c-a.su": 6.0,
    "nitter.net": 2.0,
    "news.google.com": 1.5,
}
DEFAULT_DELAY = 0.5
_last_hit = {}

def _throttle(url):
    host = urlparse(url).netloc.lower()
    delay = HOST_DELAY.get(host, DEFAULT_DELAY)
    last = _last_hit.get(host, 0)
    wait = delay - (_time.time() - last)
    if wait > 0:
        _time.sleep(wait)
    _last_hit[host] = _time.time()

def parse_feed(url, retries=3):
    """feedparser + троттлинг + ретраи с нарастающей паузой на 429."""
    for attempt in range(retries):
        _throttle(url)
        f = feedparser.parse(url, agent="Mozilla/5.0",
                            request_headers={"Cache-Control": "no-cache"})
        status = getattr(f, "status", None)
        if status == 429:
            back = (attempt + 1) * 20
            if attempt < retries - 1:
                print(f"  ⏳ 429 — пауза {back}с ({urlparse(url).netloc})")
                _time.sleep(back)
                continue
            return f, "429"
        return f, None
    return f, "429"

def make_hash(url):
    return hashlib.md5(url.encode()).hexdigest()

def extract_domain(url):
    m = re.search(r'https?://(?:www\.)?([^/]+)', url or "")
    return m.group(1).lower() if m else ""

def domain_in(domain, domain_set):
    """ФИКС: раньше сравнение было точным — news.yahoo.com не совпадал с yahoo.com
    и проскакивал мимо чёрного списка. Теперь учитываются поддомены."""
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in domain_set)

def extract_publisher(title, source):
    """Google News прячет реального издателя в хвосте заголовка после ' - '.
    Показываем 'Oneindia', а не 'GNews/Breaking' — сразу видно, кто написал."""
    if not title:
        return source, title
    m = re.match(r"^(.*?)\s+[-–—]\s+([^-–—]{2,40})$", title.strip())
    if m:
        clean_title, publisher = m.group(1).strip(), m.group(2).strip()
        # Отсекаем ложняки: "Gold prices dip - what next - analysts say"
        # Имя издания всегда с заглавной и не содержит глаголов/вопросов.
        bad = {"say", "says", "said", "next", "what", "why", "how", "here",
               "report", "reports", "analysts", "sources", "more", "update",
               "live", "watch", "video", "photos", "opinion"}
        words = publisher.split()
        looks_like_name = (
            publisher[:1].isupper()
            and len(words) <= 5
            and not any(w.lower().strip(".,!?") in bad for w in words)
        )
        if looks_like_name and len(clean_title) > 15:
            return publisher, clean_title
    return source, title

def clean_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()

# Горячие темы: если тема одна и та же, лента забивается ей.
# Иран у нас 15/30 = 50% ленты, надо сократить до 5, освободив место остальным.
TOPICS = {
    "iran-war": ["iran", "иран", "ormuz", "ормуз", "hormuz", "tehran", "тегеран", "kuwait", "кувейт"],
    "ukraine": ["ukraine", "украин", "zelensky", "зеленск", "putin", "путин", "kyiv", "киев"],
    "burnham-uk": ["burnham", "бёрнем", "бернэм", "бернхэм", "labour leader", "лейбористск"],
    "trump-elections": ["trump election", "трамп выбор", "voter fraud", "фальсификац выбор", "election fraud"],
    "china-ph": ["monkey video", "обезьян", "china daily", "west philippine sea"],
    "gold-oil": ["gold prices", "золото", "brent", "нефть", "opec", "опек", "crude oil"],
    "fed": ["fed", "фрс", "powell", "пауэлл", "warsh", "уорш", "rate hike", "rate cut"],
}

def article_topic(a):
    t = ((a.get("original_title") or "") + " " + (a.get("title") or "")).lower()
    for name, kws in TOPICS.items():
        if any(k in t for k in kws):
            return name
    return None

def _has(kw, text):
    if " " in kw:
        return kw in text
    # Русские корни без окончаний (атак, ядерн, санкци, эскалац) должны ловить
    # все словоформы: "атакует", "ядерные", "санкций". Правую границу не требуем
    # для корней 4+ символов — она отрезала все склонения.
    is_root = len(kw) >= 4 and any("а" <= c <= "я" or c == "ё" for c in kw)
    if is_root:
        pat = r"(?<![a-zа-яё0-9])" + re.escape(kw)
    else:
        pat = r"(?<![a-zа-яё0-9])" + re.escape(kw) + r"(?![a-zа-яё0-9])"
    return re.search(pat, text) is not None

STOP_SIG = {
    "the","a","an","of","in","on","to","for","and","is","as","at","by","with","from","that",
    "says","said","after","amid","over","its","his","her","new","report","reports","update",
    "по","в","на","и","о","с","за","из","что","как","это","для","от","при","до","же","бы",
    "сообщает","заявил","после","фоне","может","года","году",
}

def story_sig(article):
    """Сигнатура СЮЖЕТА по RU+EN заголовкам — ловит перепечатки с разными URL."""
    import unicodedata
    text = (article.get("original_title") or "") + " " + (article.get("title") or "")
    t = unicodedata.normalize("NFKD", text.lower())
    words = re.findall(r"[a-zа-яё0-9]+", t)
    return sorted({w for w in words if w not in STOP_SIG and len(w) > 2})

def sig_matches(sig_a, sig_b):
    a, b = set(sig_a), set(sig_b)
    if not a or not b:
        return False
    return len(a & b) / max(1, min(len(a), len(b))) >= SIM_THRESHOLD

def is_known_story(article, known_sigs):
    s = set(story_sig(article))
    if not s:
        return False
    return any(sig_matches(s, k) for k in known_sigs)

def translate_to_ru(text):
    if not text:
        return ""
    cyrillic_chars = len(re.findall(r'[а-яА-ЯёЁ]', text))
    if len(text) > 0 and (cyrillic_chars / len(text)) > 0.15:
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": text}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            result = r.json()
            translated_sentences = [sentence[0] for sentence in result[0] if sentence[0]]
            return "".join(translated_sentences).strip()
    except Exception as e:
        print(f"  ⚠ Ошибка перевода: {e}")
    return text

# URL-шаблоны нередакционных материалов (подкасты, справки)
URL_NOISE = ["/pod/", "/podcast/", "/video/", "/multimedia/", "/events/"]

def score_article(title, summary="", domain="", source="", link=""):
    tl = (title + " " + summary).lower()
    title_lower = title.lower()
    ll = (link or "").lower()
    for un in URL_NOISE:
        if un in ll: return 0
    for v in VETO_PATTERNS:
        if v in tl: return 0
    for ln in LOCAL_NOISE:
        if ln in tl: return 0
    for fn in FORMAT_NOISE:
        if fn in title_lower: return 0
    for wn in WEATHER_NOISE:
        if wn in tl: return 0
    for p in NOISE_PATTERNS:
        if p in tl: return 0
    if domain_in(domain, NOISE_DOMAINS): return 0
    for am in ANALYTICAL_MARKERS:
        if am in title_lower: return 0

    base = 0
    total_hits = 0
    strong_hits = 0
    for pts, kw_list in SCORES_MAP.items():
        for kw in kw_list:
            if _has(kw, tl):
                base = max(base, pts)
                total_hits += 1
                if pts >= 8: strong_hits += 1

    if base == 0: return 0
    is_gdelt = domain.startswith("GDELT/")
    # Для GNews домен = news.google.com, поэтому проверяем ещё и по имени издателя
    is_tier1 = domain_in(domain, TIER1_DOMAINS) or (source or "").lower() in TIER1_SOURCES
    score = base
    penalty = 0
    if total_hits == 1 and not is_tier1: penalty = 2
    if is_gdelt: penalty = max(penalty, 2)
    score = max(4, score - penalty) if penalty else score
    if strong_hits >= 2: score = min(10, score + 1)
    if is_tier1: score = min(10, score + 1)   # авторитетный источник — вверх
    # Бонус за страны аудитории канала (US/CA/UK/PH/AU)
    audience = ["u.s.", "us ", "america", "american", "washington",
                "canada", "canadian", "ottawa",
                "u.k.", "uk ", "britain", "british", "london", "westminster",
                "philippines", "philippine", "manila",
                "australia", "australian", "canberra", "sydney"]
    if any(a in tl for a in audience):
        score = min(10, score + 1)
    for bm in BREAKING_MARKERS:
        if _has(bm, tl):
            score = min(10, score + 1)
            break
    for ak in ANCHOR_KEYWORDS:
        if _has(ak, tl):
            score = min(10, score + 1)
            break
    return max(0, min(10, score))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ОСНОВНОЙ АЛГОРИТМ СБОРА ФИДОВ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def fetch_all(cutoff=None):
    articles = []
    if cutoff is None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_WINDOW)
    seen_hashes = set()

    # GDELT режет по IP, а GitHub Actions сидит на общих адресах — квота часто выбрана.
    # Берём половину запросов за запуск, чередуя. При cron 15 мин каждый запрос
    # уходит раз в полчаса, а окно 60 мин с нахлёстом ничего не теряет.
    slot = (datetime.now(TZ).hour * 60 + datetime.now(TZ).minute) // 15 % 2
    gdelt_batch = GDELT_FEEDS[slot::2]
    print(f"  🔀 GDELT: партия {slot+1}/2 — {len(gdelt_batch)} запросов")

    gdelt_ok = 0
    for url, source_name, weight in gdelt_batch:
        try:
            feed, err = parse_feed(url)
            if err:
                print(f"  ⚠ GDELT [{source_name}]: {err} после ретраев")
                continue
            for e in feed.entries[:60]:
                link = (e.get("link") or "").strip()
                if not link: continue
                h = make_hash(link)
                if h in seen_hashes: continue
                title = clean_html(e.get("title", "")).strip()
                domain = extract_domain(link)
                if not title or domain_in(domain, NOISE_DOMAINS): continue
                sc = score_article(title, "", domain, "", link)
                if sc < MIN_SCORE: continue
                pub = e.get("published_parsed") or e.get("updated_parsed")
                age_min = None
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff: continue
                    age_min = round((datetime.now(timezone.utc) - pub_dt).total_seconds() / 60, 1)
                elif sc < MIN_SCORE_UNDATED:
                    continue  # без даты — только крупное
                seen_hashes.add(h)
                gdelt_ok += 1
                # БЕЗ сети: перевод и полный текст — позже, только для новых
                articles.append({
                    "hash": h, "title": title, "original_title": title,
                                        "link": link, "source": source_name,
                    "score": sc, "weight": weight, "status": "new",
                    "ts": datetime.now(TZ).isoformat(), "age_min": age_min,
                })
        except Exception as e:
            print(f"  ⚠ GDELT [{source_name}]: {e}")
    print(f"  ✓ GDELT: {gdelt_ok} статей")

    # TG-мост тоже режет по IP — чередуем половины
    tg_feeds = [c for c in RSS_FEEDS if "tg.i-c-a.su" in c["url"]]
    other_feeds = [c for c in RSS_FEEDS if "tg.i-c-a.su" not in c["url"]]
    rss_batch = other_feeds + tg_feeds[slot::2]

    rss_ok = 0
    rss_fail = 0
    for cfg in rss_batch:
        try:
            feed, err = parse_feed(cfg["url"])
            if err:
                rss_fail += 1
                continue
            for e in feed.entries[:40]:
                link = (e.get("link") or "").strip()
                if not link: continue
                h = make_hash(link)
                if h in seen_hashes: continue
                domain = extract_domain(link)
                if domain_in(domain, NOISE_DOMAINS): continue
                pub = e.get("published_parsed") or e.get("updated_parsed")
                # ФИКС: без даты статья больше НЕ считается свежей (было age_min = 0)
                age_min = None
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff: continue
                    age_min = round((datetime.now(timezone.utc) - pub_dt).total_seconds() / 60, 1)

                title = clean_html(e.get("title", "")).strip()
                summary = clean_html(e.get("summary", ""))[:500]
                if not title: continue
                sc = score_article(title, summary, domain, cfg["source"], link)
                if sc < MIN_SCORE: continue
                if age_min is None and sc < MIN_SCORE_UNDATED:
                    continue  # без даты — только крупное
                seen_hashes.add(h)
                rss_ok += 1
                # Для Google News подменяем имя фида на реального издателя
                src = cfg["source"]
                if "news.google.com" in cfg["url"]:
                    src, title = extract_publisher(title, src)
                    sc = max(sc, score_article(title, summary, domain, src, link))
                # БЕЗ сети: перевод — позже, только для новых
                articles.append({
                    "hash": h, "title": title, "original_title": title,
                    "rss_summary": summary,
                    "link": link, "source": src,
                    "score": sc, "weight": cfg["weight"], "status": "new",
                    "ts": datetime.now(TZ).isoformat(), "age_min": age_min,
                })
        except Exception:
            rss_fail += 1
    print(f"  ✓ RSS/TG/Nitter/GNews: {rss_ok} статей ({rss_fail} фидов с ошибками)")

        # Сортировка: сначала оценённые, среди равных — свежие; без даты уходят в конец
    def sort_key(x):
        age = x.get("age_min")
        dated = 1 if age is not None else 0
        recency = -age if age is not None else -99999
        return (x["score"] * x["weight"], dated, recency)
    articles.sort(key=sort_key, reverse=True)

    import unicodedata
    STOP = {"the","a","an","of","in","on","to","for","and","is","as","at","по","в","на","и","о","с","за","из","что","как","says","said","after","amid","over","with"}
    def sig(title):
        t = unicodedata.normalize("NFKD", title.lower())
        words = re.findall(r"[a-zа-я0-9]+", t)
        words = [w for w in words if w not in STOP and len(w) > 2]
        return frozenset(words[:8])

    unique, seen_sigs = [], []
    for a in articles:
        s = sig(a["title"])
        dup = False
        for prev in seen_sigs:
            if s and prev and len(s & prev) / max(len(s), 1) >= 0.6:
                dup = True
                break
        if not dup:
            seen_sigs.append(s)
            unique.append(a)

    return unique[:TOP_N]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GIST API И ТРАНСПОРТ ДАННЫХ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEADERS = lambda: {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github+json"}

def gist_read(gist_id, filename):
    try:
        r = requests.get(f"https://api.github.com/gists/{gist_id}", headers=HEADERS(), timeout=20)
        if r.status_code == 200:
            content = r.json()["files"].get(filename, {}).get("content", "")
            return json.loads(content) if content else {}
    except Exception as e:
        print(f"  ⚠ Gist Read Error ({filename}): {e}")
    return {}

def gist_write(gist_id, filename, data):
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=HEADERS(),
            json={"files": {filename: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}},
            timeout=25
        )
        return r.status_code == 200
    except Exception as e:
        print(f"  ⚠ Gist Write Error ({filename}): {e}")
        return False

def get_raw_url(gist_id, filename):
    try:
        r = requests.get(f"https://api.github.com/gists/{gist_id}", headers=HEADERS(), timeout=15)
        if r.status_code == 200:
            files = r.json().get("files", {})
            if filename in files:
                return files[filename].get("raw_url", "")
    except Exception:
        pass
    return f"https://gist.githubusercontent.com/guzalmexmonova-ux/{gist_id}/raw/{filename}"

def get_or_create_gist():
    if GIST_ID: return GIST_ID
    try:
        r = requests.get("https://api.github.com/gists", headers=HEADERS(), timeout=15)
        if r.status_code == 200:
            for g in r.json():
                if g.get("description") == "agendalytica_data": return g["id"]
    except Exception:
        pass
    try:
        r = requests.post(
            "https://api.github.com/gists",
            headers=HEADERS(),
            json={
                "description": "agendalytica_data",
                "public": False,
                "files": {
                    "queue.json": {"content": json.dumps({"updated": "", "items": []})},
                    "analyzed.json": {"content": json.dumps({})},
                    "sent.json": {"content": json.dumps({"hashes": []})},
                    "meta.json": {"content": json.dumps({"raw_urls": {}})},
                }
            },
            timeout=25
        )
        if r.status_code == 201:
            gid = r.json()["id"]
            print(f"✅ Создан новый Gist: {gid}")
            return gid
    except Exception as e:
        print(f"❌ Ошибка критического развертывания Gist: {e}")
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ТЕЛЕГРАМ ТРАНСПОРТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def format_line(i, a, with_age=True):
    """ФИКС: без backslash внутри f-строк (SyntaxError на Python <= 3.11)."""
    age = a.get("age_min")
    # Раньше при отсутствии даты писалось "GDELT" — врало (напр. Nikkei без дат)
    age_label = f"T+{age}м" if age is not None else "без даты"
    parts = [f"<b>[{i}] {a['score']}/10</b>"]
    if with_age:
        parts.append(age_label)
    parts.append(a["source"])
    head = " | ".join(parts)
    return f"{head}\n📰 {a['title'][:150]}\n👉 <a href='{a['link']}'>Читать</a>\n"

def send_to_telegram(fresh_items, daily_items, today, is_summary=False):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠ TELEGRAM_TOKEN/CHAT_ID не настроены — пропуск отправки")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    now_str = datetime.now(TZ).strftime("%d.%m.%Y %H:%M")

    def tg_send(text):
        try:
            r = requests.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True,
            }, timeout=20)
            if r.status_code != 200:
                print(f"  ⚠ TG HTTP {r.status_code}: {r.text[:200]}")
            return r.status_code == 200
        except Exception as e:
            print(f"  ⚠ TG Error: {e}")
            return False

    def chunks(lst, n):
        for i in range(0, len(lst), n): yield lst[i:i + n]

    if fresh_items:
        header = f"🔄 <b>СВЕЖЕЕ — {now_str} TSH</b>\n📦 Новых статей: {len(fresh_items)}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        lines = [format_line(i, a, with_age=True) for i, a in enumerate(fresh_items, 1)]
        for idx, batch in enumerate(chunks(lines, 10)):
            msg = (header if idx == 0 else f"<b>СВЕЖЕЕ (продолжение {idx+1})</b>\n\n") + "\n".join(batch)
            tg_send(msg[:4000])
    else:
        print("   ✓ Новых сигналов нет")

    if is_summary and daily_items:
        header2 = f"⭐ <b>САММАРИ ДНЯ — {today}</b>\n🏆 Главное: {daily_items[0]['title'][:120]}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        lines2 = [format_line(i, a, with_age=False) for i, a in enumerate(daily_items, 1)]
        for idx, batch in enumerate(chunks(lines2, 10)):
            msg = (header2 if idx == 0 else f"<b>САММАРИ (продолжение {idx+1})</b>\n\n") + "\n".join(batch)
            tg_send(msg[:4000])

def _enrich_one(a):
    """Только перевод заголовка. Полный текст не нужен — нужна сама новость."""
    try:
        a["title"] = translate_to_ru(a["original_title"])
    except Exception as e:
        print(f"  ⚠ Перевод: {e}")
    return a

def enrich(items):
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(_enrich_one, items))
    return items

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN ORCHESTRATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    if not GIST_TOKEN:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен окружения GIST_TOKEN пуст. Завершение.")
        sys.exit(1)

    now_str = datetime.now(TZ).strftime('%d.%m.%Y %H:%M')
    print(f"🔄 Parser v6.0 — {now_str} TASHKENT ")

    gist_id = get_or_create_gist()
    if not gist_id:
        print("❌ Ошибка авторизации инфраструктуры Gist. Завершение.")
        return

    raw_url = get_raw_url(gist_id, "queue.json")
    sent = gist_read(gist_id, "sent.json")
    sent_hashes = set(sent.get("hashes", []))

    queue = gist_read(gist_id, "queue.json")
    queue_items = queue.get("items", [])
    queue_hashes = {a["hash"] for a in queue_items}

    # Скользящее окно от прошлого запуска
    now_utc = datetime.now(timezone.utc)
    last_run_raw = sent.get("last_run", "")
    cutoff = None
    if last_run_raw:
        try:
            last_run = datetime.fromisoformat(last_run_raw)
            cutoff = last_run - timedelta(minutes=OVERLAP_MIN)
        except Exception:
            cutoff = None
    floor_ = now_utc - timedelta(hours=MAX_WINDOW_H)
    ceil_ = now_utc - timedelta(hours=MIN_WINDOW_H)
    if cutoff is None:
        cutoff = now_utc - timedelta(hours=HOURS_WINDOW)
    cutoff = max(cutoff, floor_)
    cutoff = min(cutoff, ceil_)
    span = round((now_utc - cutoff).total_seconds() / 60)
    print(f"🪟 Окно: последние {span} мин (с нахлёстом {OVERLAP_MIN} мин)")

    print("📡 Парсинг источников и сбор контента...")
    articles = fetch_all(cutoff)

    # Память сюжетов за 24ч: [{"s": [слова], "ts": "..."}]
    story_log = sent.get("stories", [])
    limit_stories = datetime.now(TZ) - timedelta(hours=DEDUP_HOURS)
    fresh_log = []
    for rec in story_log:
        try:
            if datetime.fromisoformat(rec["ts"]) >= limit_stories:
                fresh_log.append(rec)
        except Exception:
            pass
    story_log = fresh_log
    known_sigs = [set(rec["s"]) for rec in story_log]
    print(f"🧠 Память сюжетов: {len(known_sigs)} за {DEDUP_HOURS}ч")

    added = 0
    skipped_stories = 0
    fresh_to_send = []
    for a in articles:
        if a["hash"] in sent_hashes or a["hash"] in queue_hashes:
            continue
        # ФИКС: перепечатка той же истории с другого URL — не отправляем
        if is_known_story(a, known_sigs):
            skipped_stories += 1
            continue
        s_new = story_sig(a)
        known_sigs.append(set(s_new))
        story_log.append({"s": s_new, "ts": datetime.now(TZ).isoformat()})
        queue_items.append(a)
        fresh_to_send.append(a)
        added += 1

    if skipped_stories:
        print(f"🔁 Отсеяно перепечаток: {skipped_stories}")
    print(f"🆕 Новых сюжетов: {added}")

    # Квота на источник: Guardian отдаёт 45 записей, NYT 58 — они забивали ленту,
    # а sort по score*weight поднимал Bloomberg/FT наверх. Теперь у всех шанс.
    if fresh_to_send:
        from collections import Counter
        # Сначала сортируем по важности — чтобы квота брала ТОП-3, а не первые попавшиеся
        fresh_to_send.sort(key=lambda a: a["score"] * a.get("weight", 1), reverse=True)
        per_source, balanced, overflow = Counter(), [], []
        for a in fresh_to_send:
            src = a.get("source", "?")
            if per_source[src] < MAX_PER_SOURCE:
                per_source[src] += 1
                balanced.append(a)
            else:
                overflow.append(a)
        if overflow:
            capped = [s for s, c in per_source.items() if c >= MAX_PER_SOURCE]
            print(f"⚖ Квота источников: отложено {len(overflow)} (лимит у {len(capped)} изданий)")
        fresh_to_send = balanced + overflow

        # Квота по темам: чтобы Иран не сжирал всю ленту
        from collections import Counter
        per_topic = Counter()
        topic_balanced, topic_overflow = [], []
        for a in fresh_to_send:
            tp = article_topic(a)
            if tp is None or per_topic[tp] < MAX_PER_TOPIC:
                per_topic[tp] += 1
                topic_balanced.append(a)
            else:
                topic_overflow.append(a)
        if topic_overflow:
            hot = [(t, c) for t, c in per_topic.items() if c >= MAX_PER_TOPIC]
            print(f"🎯 Квота тем: отложено {len(topic_overflow)} по {len(hot)} горячим сюжетам")
        fresh_to_send = topic_balanced + topic_overflow

    # Обогащаем только то, что уйдёт в Telegram
    if len(fresh_to_send) > ENRICH_LIMIT:
        print(f"✂ Обогащаю топ-{ENRICH_LIMIT} из {len(fresh_to_send)}")
        fresh_to_send = fresh_to_send[:ENRICH_LIMIT]
    if fresh_to_send:
        print(f"🌐 Перевожу заголовки: {len(fresh_to_send)}")
        enrich(fresh_to_send)

    cutoff_queue = datetime.now(TZ) - timedelta(hours=4)
    kept = []
    for a in queue_items:
        try:
            if datetime.fromisoformat(a["ts"]) >= cutoff_queue:
                kept.append(a)
        except Exception:
            pass
    queue_items = kept
    queue_items.sort(key=lambda x: (x["score"] * x["weight"], x["ts"]), reverse=True)
    queue_items = queue_items[:50]

    gist_write(gist_id, "queue.json", {
        "updated": datetime.now(TZ).isoformat(), "raw_url": raw_url, "total": len(queue_items), "items": queue_items
    })

    with open("news_queue.json", "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(TZ).isoformat(), "items": queue_items}, f, ensure_ascii=False, indent=2)

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    from pathlib import Path
    daily_file = Path("daily_best.json")
    try:
        daily = json.loads(daily_file.read_text(encoding="utf-8")) if daily_file.exists() else {"date": today, "items": []}
    except Exception:
        daily = {"date": today, "items": []}
    if daily.get("date") != today: daily = {"date": today, "items": []}

    daily_hashes = {a["hash"] for a in daily["items"]}
    for a in queue_items:
        if a["hash"] not in daily_hashes: daily["items"].append(a)

    daily["items"].sort(key=lambda x: x["score"] * x["weight"], reverse=True)
    daily["items"] = daily["items"][:20]
    daily["updated"] = datetime.now(TZ).isoformat()
    daily_file.write_text(json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8")

    now_iso = datetime.now(TZ).isoformat()
    sent_records = sent.get("records", [])
    existing = {r["h"] for r in sent_records}
    for a in fresh_to_send:
        if a["hash"] not in existing: sent_records.append({"h": a["hash"], "ts": now_iso})

    keep_records = []
    limit = datetime.now(TZ) - timedelta(hours=24)
    for r in sent_records:
        try:
            if datetime.fromisoformat(r["ts"]) >= limit:
                keep_records.append(r)
        except Exception:
            pass
    sent_records = keep_records

    now_tsh = datetime.now(TZ)
    last_summary_date = sent.get("last_summary_date", "")
    is_summary = (now_tsh.hour == 20) and last_summary_date != today

    gist_write(gist_id, "sent.json", {
        "hashes": [r["h"] for r in sent_records],
        "records": sent_records,
        "stories": story_log[-400:],
        "last_run": now_utc.isoformat(),
        "last_summary_date": today if is_summary else last_summary_date
    })

    # Сторож от гонки убран: он резал СВОИ же новости.
    # cron-job.org — единственный триггер, GitHub-cron отключён,
    # параллельных запусков быть не должно. Если начнут случаться —
    # добавим блокировку через Gist, а не по хэшам.

    send_to_telegram(fresh_to_send, daily["items"], today, is_summary)
    print("✅ Скрипт успешно завершил цикл обработки.")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n💥 КРИТИЧЕСКИЙ СБОЙ ПРИ ВЫПОЛНЕНИИ:")
        traceback.print_exc()
        sys.exit(1)
