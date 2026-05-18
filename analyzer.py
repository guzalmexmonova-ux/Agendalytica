#!/usr/bin/env python3
"""
AGENDALYTICA — ANALYZER
Берёт 1 статью из очереди → Gemini (перевод + анализ) → analyzed.json
Запускается каждые 6 минут через GitHub Actions
"""

import requests
import json
import re
import os
from datetime import datetime, timedelta, timezone

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIST_TOKEN   = os.environ.get("GIST_TOKEN", "")
GIST_ID      = os.environ.get("GIST_ID", "")
GEMINI_KEYS  = [k.strip() for k in os.environ.get("GEMINI_API_KEY", "").split(",") if k.strip()]
TZ           = timezone(timedelta(hours=5))

GEMINI_MODELS = [
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
]

_key_idx = 0

def get_key():
    if not GEMINI_KEYS: return ""
    return GEMINI_KEYS[_key_idx % len(GEMINI_KEYS)]

def rotate_key():
    global _key_idx
    _key_idx += 1

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GEMINI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROMPT = """Ты — главный редактор Telegram-канала AGENDALYTICA (геополитика, экономика).
Аудитория: думающие люди 25-45 лет.

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

def gemini_call(prompt):
    if not GEMINI_KEYS: return None
    key = get_key()
    for model in ["google/gemini-2.0-flash-exp:free","meta-llama/llama-3.3-70b-instruct:free","mistralai/mistral-7b-instruct:free"]:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","HTTP-Referer":"https://agendalytica.com","X-Title":"Agendalytica"},
                json={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.4,"max_tokens":1500},
                timeout=30
            )
            if r.status_code == 429:
                print(f"  ⏳ Rate limit {model} — следующая модель")
                continue
            if r.status_code != 200:
                print(f"  ⚠ OpenRouter {r.status_code}: {r.text[:80]}")
                continue
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text:
                print(f"  ✅ OpenRouter: {model.split('/')[1]}")
                return text
        except Exception as e:
            print(f"  ⚠ OpenRouter error: {e}")
            continue
    return None

def analyze_article(article):
    prompt = PROMPT.format(
        title   = article.get("title",""),
        summary = article.get("summary","")[:500],
        source  = article.get("source",""),
    )
    result = gemini_call(prompt)
    if not result:
        print("  ⚠ Gemini не ответил")
        return None
    try:
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            if data.get("title_ru"):
                return data
    except Exception as e:
        print(f"  ⚠ JSON parse error: {e}")
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
            content = r.json()["files"].get(filename, {}).get("content","")
            return json.loads(content) if content else {}
    except: pass
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
    except: return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    print(f"🤖 Analyzer запущен — {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} TASHKENT")

    if not GIST_ID:
        print("❌ GIST_ID не задан")
        return

    # Читаем очередь
    queue = gist_read("queue.json")
    items = queue.get("items", [])

    # Читаем уже проанализированные
    analyzed = gist_read("analyzed.json")
    analyzed_items = analyzed.get("items", [])
    analyzed_hashes = {a["hash"] for a in analyzed_items}

    # Берём топ-1 не проанализированную (самую вирусную)
    pending = [a for a in items if a["hash"] not in analyzed_hashes]

    if not pending:
        print("✓ Нет новых статей для анализа")
        return

    article = pending[0]
    print(f"📝 Анализируем: [{article['score']}/10] [{article['source']}]")
    print(f"   {article['title'][:80]}")

    if not GEMINI_KEYS:
        print("❌ Нет Gemini ключей")
        return

    analysis = analyze_article(article)

    if not analysis:
        print("❌ Анализ не удался")
        return

    print(f"✅ Gemini анализ готов | viral={analysis.get('viral_score',0)}")

    # Добавляем в analyzed
    analyzed_items.append({
        **article,
        "analysis": analysis,
        "analyzed_at": datetime.now(TZ).isoformat(),
        "status": "analyzed",
    })

    # Держим последние 200
    analyzed_items = analyzed_items[-200:]

    ok = gist_write("analyzed.json", {
        "updated": datetime.now(TZ).isoformat(),
        "items": analyzed_items
    })

    if ok:
        print(f"✅ Сохранено в analyzed.json")
    else:
        print("❌ Ошибка записи")

if __name__ == "__main__":
    main()
