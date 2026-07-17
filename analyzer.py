#!/usr/bin/env python3
"""
AGENDALYTICA — ANALYZER v2 (с семантическим дедупом)
Берёт 1 статью из очереди → OpenRouter → analyzed.json
НОВОЕ: отсекает одну и ту же историю от разных источников за 24ч
"""

import requests
import json
import re
import os
import unicodedata
from datetime import datetime, timedelta, timezone

GIST_TOKEN  = os.environ.get("GIST_TOKEN", "")
GIST_ID     = os.environ.get("GIST_ID", "")
OR_KEYS     = [k.strip() for k in os.environ.get("GEMINI_API_KEY", "").split(",") if k.strip()]
TZ          = timezone(timedelta(hours=5))

OR_URL      = "https://openrouter.ai/api/v1/chat/completions"
OR_MODELS   = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super:free",
]

DEDUP_HOURS = 24     # окно памяти историй
SIM_THRESHOLD = 0.45 # порог схожести (было 0.6 — слишком мягко)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  СЕМАНТИЧЕСКИЙ ДЕДУП
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STOP = {
    "the","a","an","of","in","on","to","for","and","is","as","at","by","with","from","that",
    "says","said","after","amid","over","its","his","her","new","report","reports","update",
    "по","в","на","и","о","с","за","из","что","как","это","для","от","при","до","же","бы",
    "сообщает","заявил","после","фоне","может","года","году",
}

def sig(article):
    """Сигнатура истории по RU+EN заголовкам."""
    text = (article.get("original_title") or "") + " " + (article.get("title") or "")
    t = unicodedata.normalize("NFKD", text.lower())
    words = re.findall(r"[a-zа-яё0-9]+", t)
    words = [w for w in words if w not in STOP and len(w) > 2]
    return frozenset(words)

def is_dup(article, prev_sigs):
    s = sig(article)
    if not s:
        return False
    for p in prev_sigs:
        if not p:
            continue
        inter = len(s & p)
        # доля пересечения относительно меньшего набора
        ratio = inter / max(1, min(len(s), len(p)))
        if ratio >= SIM_THRESHOLD:
            return True
    return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ПРОМПТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROMPT = """IMPORTANT: Respond ONLY with valid JSON. No markdown, no explanation, no Chinese characters, no extra text. Start your response with {{ and end with }}.
You are the editor of AGENDALYTICA Telegram channel (geopolitics, economics).

НОВОСТЬ:
Заголовок: {title}
Содержание: {summary}
Источник: {source}

Сделай в ОДНОМ ответе: перевод + глубокий анализ.
Отвечай СТРОГО валидным JSON без markdown:
{{
  "title_ru": "Полный перевод заголовка на русский без обрезки",
  "title_en": "Заголовок на английском (если уже EN — оставь как есть)",
  "sut_ru": "Что случилось — 3 предложения: конкретные факты, имена, детали. Не копируй заголовок.",
  "sut_en": "What happened — 3 sentences: facts, names, details. No headline copy.",
  "vazhno_ru": "Почему важно — 2-3 предложения: масштаб, влияние на рынки/страны/людей.",
  "vazhno_en": "Why it matters — 2-3 sentences: scale, impact on markets/countries/people.",
  "kontekst_ru": "Скрытый контекст — 1-2 предложения: интересы сторон, что не пишут в заголовках.",
  "kontekst_en": "Hidden context — 1-2 sentences: parties' interests, what headlines miss.",
  "prognoz_ru": "Прогноз 24-72ч — 2 предложения: что конкретно произойдёт, за чем следить.",
  "prognoz_en": "Forecast 24-72h — 2 sentences: what to expect, what to watch.",
  "viral_score": 0,
  "short_title": "Заголовок для Reels/Shorts — цепляет за 3 секунды",
  "short_hook": "Крючок — первая фраза видео",
  "long_title": "",
  "long_hook": "",
  "long_angle": "",
  "long_structure": []
}}
viral_score 1-10 (10=10млн+ просмотров).
Если viral_score >= 7 — заполни long_title, long_hook, long_angle, long_structure (4 блока).
ТРЕБОВАНИЕ: реальный анализ, никаких шаблонов."""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  OPENROUTER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def ai_call(prompt):
    if not OR_KEYS:
        print("❌ Нет API ключей")
        return None
    key = OR_KEYS[0]
    for model in OR_MODELS:
        try:
            r = requests.post(
                OR_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://agendalytica.com",
                    "X-Title": "Agendalytica",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 1500,
                },
                timeout=30
            )
            if r.status_code == 429:
                print(f"  ⏳ Rate limit {model} — следующая")
                continue
            if r.status_code != 200:
                print(f"  ⚠ {r.status_code}: {r.text[:100]}")
                continue
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text:
                print(f"  ✅ {model.split('/')[1]}")
                return text
        except Exception as e:
            print(f"  ⚠ error: {e}")
            continue
    return None

def analyze_article(article):
    prompt = PROMPT.format(
        title   = article.get("title", ""),
        summary = article.get("summary", "")[:500],
        source  = article.get("source", ""),
    )
    result = ai_call(prompt)
    if not result:
        print("  ⚠ AI не ответил")
        return None
    try:
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            if data.get("title_ru"):
                return data
    except Exception as e:
        print(f"  ⚠ JSON error: {e}")
        print(f"  Raw: {result[:300] if result else 'None'}")
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GIST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def gist_read(filename):
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            timeout=10
        )
        if r.status_code == 200:
            content = r.json()["files"].get(filename, {}).get("content", "")
            return json.loads(content) if content else {}
    except Exception:
        pass
    return {}

def gist_write(filename, data):
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={"Authorization": f"token {GIST_TOKEN}"},
            json={"files": {filename: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}},
            timeout=10
        )
        return r.status_code == 200
    except Exception:
        return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    print(f"🤖 Analyzer v2 — {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} TASHKENT")

    if not GIST_ID:
        print("❌ GIST_ID не задан"); return

    queue    = gist_read("queue.json")
    items    = queue.get("items", [])
    analyzed = gist_read("analyzed.json")
    analyzed_items  = analyzed.get("items", [])
    analyzed_hashes = {a["hash"] for a in analyzed_items}

    # Сигнатуры уже разобранных историй за последние 24ч
    limit = datetime.now(TZ) - timedelta(hours=DEDUP_HOURS)
    recent_sigs = []
    for a in analyzed_items:
        try:
            when = datetime.fromisoformat(a.get("analyzed_at", ""))
            if when >= limit:
                recent_sigs.append(sig(a))
        except Exception:
            continue
    print(f"🧠 История дедупа: {len(recent_sigs)} сюжетов за {DEDUP_HOURS}ч")

    # Кандидаты: не по хэшу И не по смыслу
    pending = []
    skipped_dup = 0
    for a in items:
        if a["hash"] in analyzed_hashes:
            continue
        if is_dup(a, recent_sigs):
            skipped_dup += 1
            continue
        pending.append(a)

    if skipped_dup:
        print(f"🔁 Отсеяно дублей-перепечаток: {skipped_dup}")

    if not pending:
        print("✓ Нет новых сюжетов"); return

    article = pending[0]
    print(f"📝 [{article['score']}/10] [{article['source']}]")
    print(f"   {article['title'][:80]}")

    analysis = analyze_article(article)
    if not analysis:
        print("❌ Анализ не удался"); return

    print(f"✅ Анализ готов | viral={analysis.get('viral_score', 0)}")

    analyzed_items.append({
        **article,
        "analysis":    analysis,
        "analyzed_at": datetime.now(TZ).isoformat(),
        "status":      "analyzed",
    })
    analyzed_items = analyzed_items[-200:]

    ok = gist_write("analyzed.json", {
        "updated": datetime.now(TZ).isoformat(),
        "items":   analyzed_items
    })
    print("✅ Сохранено" if ok else "❌ Ошибка записи")

if __name__ == "__main__":
    main()
