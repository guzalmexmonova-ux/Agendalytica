#!/usr/bin/env python3
"""
AGENDALYTICA — SENDER
Берёт проанализированную статью → форматирует → отправляет в Telegram
Запускается каждые 6 минут через GitHub Actions
"""

import requests
import json
import re
import os
from datetime import datetime, timedelta, timezone

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIST_TOKEN       = os.environ.get("GIST_TOKEN", "")
GIST_ID          = os.environ.get("GIST_ID", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TZ               = timezone(timedelta(hours=5))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  ФОРМАТИРОВАНИЕ ПОСТА
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def esc(t):
    return str(t or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def get_category(analysis, title_ru):
    tl = str(title_ru).lower()
    if any(x in tl for x in ["война","атака","конфликт","вторжен","удар","ракета"]):
        return "⚔️ ВОЙНА & ГЕОПОЛИТИКА / WAR & GEOPOLITICS"
    if any(x in tl for x in ["министр","президент","премьер","визит","саммит","переговоры"]):
        return "💼 ПОЛИТИКА & ДИПЛОМАТИЯ / POLITICS & DIPLOMACY"
    if any(x in tl for x in ["нефть","газ","золото","опек","уран","энергетик"]):
        return "🛢 ЭНЕРГЕТИКА & РЕСУРСЫ / ENERGY & RESOURCES"
    if any(x in tl for x in ["ставка","фрс","рецессия","инфляция","дефолт","рынок","облигаци"]):
        return "📈 ЭКОНОМИКА & РЫНКИ / ECONOMY & MARKETS"
    if any(x in tl for x in ["чип","полупроводник","кибератака","технологи","санкци"]):
        return "💾 ТЕХНОЛОГИИ / TECH & CYBER"
    if any(x in tl for x in ["узбекистан","казахстан","центральная азия","мирзиёев","токаев"]):
        return "🇺🇿 ЦЕНТРАЛЬНАЯ АЗИЯ / CENTRAL ASIA"
    return "🛰 ГЕОПОЛИТИКА / GEOPOLITICS"

def format_post(item):
    a       = item.get("analysis", {})
    ts      = datetime.now(TZ).strftime("%d.%m.%Y | %H:%M")
    scale   = item.get("score", 0)
    src     = esc(item.get("source",""))
    link    = item.get("link","")
    cat     = get_category(a, a.get("title_ru",""))
    bar     = "🔴" * min(scale, 5)
    viral   = int(a.get("viral_score", 0) or 0)

    title_ru = esc(a.get("title_ru","") or item.get("title",""))
    title_en = esc(a.get("title_en","") or item.get("title",""))

    label = "⚡️ <b>[ ТОЛЬКО ЧТО / BREAKING ]</b>" if scale >= 9 else "🚨 <b>[ СРОЧНО / URGENT ]</b>"

    # Блоки анализа
    def block(emoji, label_ru, label_en, val_ru, val_en):
        ru = esc(str(val_ru or "")).strip()
        en = esc(str(val_en or "")).strip()
        if not ru and not en: return ""
        lines = [f"{emoji} <b>{label_ru} / {label_en}:</b>"]
        if ru: lines.append(f"🇷🇺 <i>{ru}</i>")
        if en: lines.append(f"🇺🇸 <i>{en}</i>")
        return "\n".join(lines)

    analysis_blocks = "\n\n".join(filter(None, [
        block("🔹", "Что случилось", "What happened",
              a.get("sut_ru"), a.get("sut_en")),
        block("🔍", "Почему важно", "Why it matters",
              a.get("vazhno_ru"), a.get("vazhno_en")),
        block("🕵️", "Скрытый контекст", "Hidden context",
              a.get("kontekst_ru"), a.get("kontekst_en")),
        block("⚡️", "Прогноз 24-72ч", "Forecast 24-72h",
              a.get("prognoz_ru"), a.get("prognoz_en")),
    ]))

    # Основной пост
    post = (
        f"{label}\n"
        f"📂 <code>{esc(cat)}</code>\n"
        f"🗞 <b>Источник:</b> <code>{src}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <code>{ts} TASHKENT (GMT+5)</code>\n"
        f"📊 <b>Масштаб:</b> {bar} <b>({scale}/10)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🇷🇺 <b>{title_ru}</b>\n\n"
        f"🇺🇸 <b>{title_en}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{analysis_blocks}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <a href=\"{link}\">Читать полностью / Read full story → {src}</a>\n"
        f"📺 @Agendalytica"
    )

    messages = [post]

    # Второй пост — вирусный потенциал для Reels
    if viral > 0 and a.get("short_title"):
        msg2 = (
            f"📱 <b>Вирусный потенциал</b> {'⭐'*min(viral,10)} <b>({viral}/10)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Reels/Shorts:</b>\n<b>{esc(a.get('short_title',''))}</b>\n\n"
            f"🧲 <b>Крючок (первые 3 сек):</b>\n<i>{esc(a.get('short_hook',''))}</i>"
        )
        messages.append(msg2)

    # Третий пост — лонг если viral >= 7
    if viral >= 7 and a.get("long_title"):
        struct = a.get("long_structure", [])
        sl = "\n".join(f"  {i+1}. {esc(str(b))}" for i, b in enumerate(struct[:6]))
        msg3 = (
            f"🎬 <b>Лонг YouTube</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>{esc(a.get('long_title',''))}</b>\n\n"
            f"🎤 <b>Интро:</b> <i>{esc(a.get('long_hook',''))}</i>\n\n"
            f"🔍 <b>Угол:</b> {esc(a.get('long_angle',''))}\n\n"
            f"📋 <b>Структура:</b>\n{sl}"
        )
        messages.append(msg3)

    return messages

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_telegram(text, link=""):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     text,
                "parse_mode":               "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15
        )
        if r.status_code == 200: return True
        if r.status_code == 400:
            # Fallback без HTML
            plain = re.sub(r'<[^>]+>', '', text)
            r2 = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": plain[:4000]},
                timeout=15
            )
            return r2.status_code == 200
        print(f"  ⚠ TG {r.status_code}: {r.text[:100]}")
    except Exception as e:
        print(f"  ⚠ TG error: {e}")
    return False

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
    print(f"📤 Sender запущен — {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} TASHKENT")

    if not GIST_ID:
        print("❌ GIST_ID не задан")
        return

    # Читаем проанализированные
    analyzed = gist_read("analyzed.json")
    items    = analyzed.get("items", [])

    # Читаем уже отправленные
    sent      = gist_read("sent.json")
    sent_hashes = set(sent.get("hashes", []))

    # Берём первую готовую и не отправленную
    pending = [a for a in items if a["hash"] not in sent_hashes and a.get("status") == "analyzed"]

    if not pending:
        print("✓ Нет новых статей для отправки")
        return

    item = pending[0]
    a    = item.get("analysis", {})
    print(f"📨 Отправляем: [{item['score']}/10] [{item['source']}]")
    print(f"   {a.get('title_ru', item['title'])[:80]}")

    messages = format_post(item)
    success  = True

    for i, msg in enumerate(messages):
        ok = send_telegram(msg, item.get("link",""))
        if ok:
            print(f"  ✅ Сообщение {i+1}/{len(messages)} отправлено")
        else:
            print(f"  ❌ Сообщение {i+1} не отправлено")
            success = False
        if i < len(messages) - 1:
            import time; time.sleep(2)

    if success:
        # Помечаем как отправленное
        sent_hashes.add(item["hash"])
        gist_write("sent.json", {
            "updated": datetime.now(TZ).isoformat(),
            "hashes": list(sent_hashes)[-500:]
        })
        print(f"✅ Готово!")
    else:
        print("❌ Ошибка отправки")

if __name__ == "__main__":
    main()
