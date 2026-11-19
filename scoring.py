#!/usr/bin/env python3
"""
AGENDALYTICA — вторичная оценка важности (v2).

parser.score_article() даёт СЫРОЙ балл по ключевым словам (он же решает, попадает ли
статья в очередь — этот порог не менялся). Здесь сырой балл пересчитывается в
итоговый `score`: 9–10 становятся редкими, колонки/мнения/мелочь понижаются,
подтверждение несколькими изданиями, официальные источники и крупные регионы повышают.
Чистые функции, без сети — легко тестируются.
"""
import re
from urllib.parse import urlparse

IMPORTANT_MIN = 7    # «важное» — идёт в сводку
URGENT_MIN = 9       # «срочное» — можно отправить сразу

OFFICIAL_DOMAINS = {
    "federalreserve.gov", "ecb.europa.eu", "un.org", "whitehouse.gov", "nato.int",
    "defense.gov", "state.gov", "imf.org", "bis.org", "kremlin.ru", "mid.ru",
    "gov.uk", "europa.eu", "fmprc.gov.cn", "iaea.org", "treasury.gov", "truthsocial.com",
}
OFFICIAL_SOURCES = {"fed", "ecb", "un", "whitehouse/x", "potus/x", "pentagon", "iaea", "eu commission", "boe"}

# Агентства/топ-издания: одиночное сообщение может дойти до 7 (остальным нужно подтверждение)
WIRE_SOURCES = {"reuters", "ap", "ap news", "afp", "bloomberg", "ft", "bbc", "bbc world", "wsj", "nyt world",
                "the new york times", "tg/bloomberg"}
WIRE_DOMAINS = {"reuters.com", "apnews.com", "bloomberg.com", "ft.com", "bbc.com", "bbc.co.uk", "wsj.com", "nytimes.com"}

# Признаки колонок/мнений/обзоров/интервью (в URL и в заголовке)
OPINION_URL = ["/opinion", "/opinions/", "/comment/", "/commentisfree", "/column", "/columns/",
               "/analysis/", "/editorial", "/viewpoint", "/perspective", "/blog", "/long-read",
               "/longread", "/review", "/interview", "/explainer", "/op-ed", "/oped", "/voices/",
               "/ideas/", "/features/", "/feature/", "/lifestyle", "/magazine/", "/mnenie", "/opinions"]
OPINION_TITLE = ["opinion:", "opinion |", "| opinion", "analysis:", "analysis |", "| analysis",
                 "comment:", "column:", "editorial:", "op-ed", "commentary", "explainer:",
                 "review:", "interview:", "feature:", "viewpoint", "the big read", "long read",
                 "мнение", "колонка", "комментарий:", "аналитика:", "обзор:", "интервью:", "разбор:", "эксперт:"]
SOFT_START = ("why ", "how ", "what ", "who ", "is it ", "should ", "can ", "could ",
              "почему ", "как ", "что будет", "зачем ")

# Мелкие дипломатические/протокольные новости
MINOR_MARKERS = ["envoy", "ambassador", "consul", "goodwill", "trade mission", "cultural exchange",
                 "посланник", "посол ", "консул", "культурный обмен"]

# Регионы, важные русскоязычной аудитории
REGION_KEYS = [
    # Россия
    "russia", "russian", "putin", "kremlin", "moscow", "росси", "путин", "кремл", "москв",
    # Украина
    "ukrain", "kyiv", "kiev", "zelensky", "украин", "киев", "зеленск",
    # Узбекистан / ЦА
    "uzbek", "tashkent", "kazakh", "kyrgyz", "tajik", "turkmen", "central asia", "mirziyoyev",
    "узбек", "ташкент", "казах", "кыргыз", "киргиз", "таджик", "туркмен", "центральн", "мирзиёев",
    # США
    "u.s.", "united states", "washington", "trump", "white house", "pentagon", "federal reserve",
    "congress", "wall street", "сша", "америк", "трамп", "вашингтон", "белый дом", "пентагон", "фрс", "конгресс",
    # Европа
    "europe", "european", "brussels", "nato", "germany", "france", "britain", "ecb", "eu", "uk",
    "европ", "нато", "брюссел", "германи", "франци", "британи", "ес ", "еврокомисс",
    # Китай
    "china", "chinese", "beijing", "xi jinping", "taiwan", "китай", "пекин", "си цзиньпин", "тайван",
    # Ближний Восток
    "israel", "gaza", "iran", "saudi", "syria", "lebanon", "hezbollah", "houthi", "yemen", "iraq",
    "hamas", "израил", "газа", "иран", "саудов", "сири", "ливан", "хезболл", "хуси", "йемен", "ирак", "хамас",
]


def _has(kw, text):
    cyr = any("а" <= c <= "я" or c == "ё" for c in kw)
    if cyr and len(kw) >= 3 and not kw.endswith(" "):
        pat = r"(?<![a-zа-яё0-9])" + re.escape(kw)            # корень: любые окончания
    else:
        pat = r"(?<![a-zа-яё0-9])" + re.escape(kw.strip()) + r"(?![a-zа-яё0-9])"
    return re.search(pat, text) is not None


def domain_of(link):
    try:
        d = urlparse(link or "").netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def is_official(link="", source=""):
    d = domain_of(link)
    if any(d == o or d.endswith("." + o) for o in OFFICIAL_DOMAINS):
        return True
    return (source or "").lower() in OFFICIAL_SOURCES


def opinion_kind(title, link=""):
    """'opinion' (колонка/мнение/обзор/интервью/feature), 'soft' (вопрос-эссе) или None."""
    t = (title or "").strip().lower()
    ll = (link or "").lower()
    if any(m in ll for m in OPINION_URL) or any(m in t for m in OPINION_TITLE):
        return "opinion"
    if t.endswith("?") or t.endswith("?»") or t.endswith("?\""):
        return "soft"
    if t.startswith(SOFT_START) and len(t) > 35:
        return "soft"
    return None


def region_hit(text):
    return any(_has(k, text) for k in REGION_KEYS)


def finalize_score(raw, title, summary="", link="", source="", n_sources=1, translated_title=""):
    """Итоговый балл 1..10 из сырого. Возвращает (score, reasons)."""
    reasons = []
    if raw <= 0:
        return 0, reasons
    # Сжатие верха шкалы: сырые 9–10 ставились почти всему («war», «attack» в любом заголовке)
    s = raw - 3 if raw >= 9 else raw - 3 if raw == 8 else raw - 2 if raw == 7 else raw - 2 if raw == 6 else raw
    text = f"{title} {translated_title} {summary}".lower()
    official = is_official(link, source)
    n = max(1, int(n_sources or 1))

    if official:
        s += 1; reasons.append("official")
    if n >= 4:
        s += 3; reasons.append(f"confirmed x{n}")
    elif n == 3:
        s += 2; reasons.append(f"confirmed x{n}")
    elif n == 2:
        s += 1; reasons.append("confirmed x2")
    in_region = region_hit(text)
    if not in_region and not official:
        s -= 2; reasons.append("no-priority-region")

    kind = opinion_kind(title, link) or opinion_kind(translated_title)
    if kind == "opinion":
        s = min(s - 3, 5); reasons.append("opinion")
    elif kind == "soft":
        s = min(s - 2, 6); reasons.append("question/explainer")

    if n < 2 and not official and any(_has(m, text) for m in MINOR_MARKERS):
        s -= 2; reasons.append("minor-diplomatic")

    # Лестница: 7 — достаточно одного издания; 8 — подтверждено (2+ изданий или официальный источник);
    # 9 — 3+ изданий или официальный + 2 издания; 10 — 4+ изданий и важный регион.
    cap = 7 if (source or "").lower() in WIRE_SOURCES or domain_of(link) in WIRE_DOMAINS else 6
    if n >= 2 or official: cap = 8
    if n >= 3 or (official and n >= 2): cap = 9
    if n >= 4 and in_region: cap = 10
    if s > cap:
        reasons.append(f"cap{cap}"); s = cap
    return max(1, min(10, s)), reasons


def rescore_article(a):
    """Пересчёт одной статьи-словаря (поля как в parser.fetch_all). Меняет a['score'], сохраняет a['score_raw']."""
    raw = a.get("score_raw", a.get("score", 0))
    a["score_raw"] = raw
    a["sources_count"] = a.get("sources_count", 1)
    a["score"], _ = finalize_score(
        raw, a.get("original_title") or a.get("title", ""), a.get("rss_summary", ""),
        a.get("link", ""), a.get("source", ""), a["sources_count"],
    )
    return a
