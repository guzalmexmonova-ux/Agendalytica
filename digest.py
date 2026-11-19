#!/usr/bin/env python3
"""
AGENDALYTICA — сводка в Telegram каждый час (по Ташкенту, UTC+5) + срочные отдельно.

Состояние живёт в sent.json (Gist) под ключом "digest": каждый запуск Actions — новый runner,
поэтому ничего не хранится локально. Чистая логика: отправка передаётся функцией send(text)->bool.
"""
import html
import re
from datetime import datetime, timedelta, timezone

import scoring

TZ = timezone(timedelta(hours=5))
SLOT_HOURS = tuple(range(24))   # сводка каждый час по Ташкенту (решение владельца 19.11); пустые не отправляются
IMPORTANT_MIN = scoring.IMPORTANT_MIN        # 7
URGENT_MIN = scoring.URGENT_MIN              # 9
URGENT_GAP = timedelta(hours=1)              # срочные — не чаще 1 раза в час
NEW_LIMIT = 10                               # макс. строк в блоке «Новое»
TOP_LIMIT = 5                                # макс. строк в блоке «Главное за день»
KEEP_ITEMS = 120                             # потолок записей важного за день в состоянии

_STOP = {"the", "a", "an", "of", "in", "on", "to", "for", "and", "is", "as", "at", "by", "with", "from",
         "that", "says", "said", "after", "amid", "over", "its", "his", "her", "new", "по", "в", "на", "и",
         "о", "с", "за", "из", "что", "как", "это", "для", "от", "при", "до"}


def _sig(title):
    return sorted({w for w in re.findall(r"[a-zа-яё0-9]+", (title or "").lower()) if w not in _STOP and len(w) > 2})


def _same_story(a, b, thr=0.45):
    a, b = set(a), set(b)
    return bool(a and b) and len(a & b) / max(1, min(len(a), len(b))) >= thr


def esc(t):
    return html.escape(str(t or ""), quote=False)


def new_state(today):
    return {"date": today, "last_digest_at": "", "last_urgent_at": "",
            "total": 0, "items": {}}


def load_state(raw, now):
    """Состояние из sent.json["digest"]; на новый день счётчики и список сбрасываются, времена — нет."""
    today = now.strftime("%Y-%m-%d")
    st = dict(raw) if isinstance(raw, dict) and raw else new_state(today)
    st.setdefault("last_digest_at", ""); st.setdefault("last_urgent_at", "")
    if st.get("date") != today:
        st = {**new_state(today), "last_digest_at": st["last_digest_at"], "last_urgent_at": st["last_urgent_at"]}
    st.setdefault("items", {}); st.setdefault("total", 0)
    return st


def _parse(ts):
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=TZ)
    except Exception:
        return None


def slot_start(now):
    """Начало текущего 3-часового слота (по Ташкенту)."""
    hrs = [h for h in SLOT_HOURS if h <= now.hour]
    return now.replace(hour=max(hrs), minute=0, second=0, microsecond=0)


def digest_due(state, now):
    """Пора ли слать сводку: в текущем слоте её ещё не было. Первый запуск (пусто) — шлём."""
    last = _parse(state.get("last_digest_at", ""))
    return last is None or last < slot_start(now)


def urgent_allowed(state, now):
    last = _parse(state.get("last_urgent_at", ""))
    return last is None or now - last >= URGENT_GAP


def register(state, fresh, now, total_added=None):
    """Учесть свежие статьи запуска: счётчик «всего» и запись важных."""
    state["total"] = state.get("total", 0) + (total_added if total_added is not None else len(fresh))
    for a in fresh:
        if a.get("score", 0) < IMPORTANT_MIN:
            continue
        h = a["hash"]
        if h in state["items"]:
            continue
        state["items"][h] = {
            "t": a.get("title", ""), "s": a["score"], "src": a.get("source", ""), "link": a.get("link", ""),
            "n": a.get("sources_count", 1), "srcs": [a.get("source", "")] + list(a.get("also", [])),
            "raw": a.get("score_raw", a["score"]), "sig": _sig(a.get("original_title") or a.get("title")),
            "first": now.isoformat(timespec="minutes"), "digest": "", "urgent": False,
        }
    if len(state["items"]) > KEEP_ITEMS:       # держим самые важные и свежие
        keep = sorted(state["items"].items(), key=lambda kv: (kv[1]["s"], kv[1]["first"]), reverse=True)[:KEEP_ITEMS]
        state["items"] = dict(keep)
    return state


def bump(state, article):
    """Перепечатка уже известного сюжета другим изданием = подтверждение: пересчитать балл записи."""
    sg = _sig(article.get("original_title") or article.get("title"))
    for it in state["items"].values():
        if _same_story(sg, it["sig"]):
            src = article.get("source", "")
            if src and src not in it["srcs"]:
                it["srcs"].append(src)
                it["n"] = len(it["srcs"])
                new, _ = scoring.finalize_score(it["raw"], it["t"], "", it["link"], it["src"], it["n"])
                it["s"] = max(it["s"], new)
            return True
    return False


def _line(i, it, mark=""):
    conf = f" · {it['n']} изд." if it.get("n", 1) >= 2 else ""
    title = esc(it["t"])[:150]
    return (f"<b>{i}. {it['s']}/10</b> · {esc(it['src'])}{conf}{mark}\n"
            f"{title}\n<a href='{esc(it['link'])}'>Читать</a>\n")


def build_urgent(it, now):
    return (f"🚨 <b>СРОЧНО — {now.strftime('%H:%M')} TSH</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + _line(1, it).replace("<b>1. ", "<b>"))


def build_digest(state, now, new_keys):
    """Текст сводки. new_keys — ключи важного, ещё не входившего ни в одну сводку и не слитого как срочное."""
    items = state["items"]
    important = len(items)
    hh = now.strftime("%H:%M")
    head = f"🗓 <b>СВОДКА {hh} TSH</b> · {now.strftime('%d.%m')}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    new = sorted((items[k] for k in new_keys), key=lambda x: (x["s"], x["n"]), reverse=True)[:NEW_LIMIT]
    parts = [head, "🆕 <b>Новое за последний час</b>\n"]
    parts += [_line(i, it) for i, it in enumerate(new, 1)] if new else ["— ничего нового важного\n"]
    parts.append(f"\n📊 <b>За сегодня собрано: {important} важных / {state.get('total', 0)} всего</b>\n")
    top = sorted(items.items(), key=lambda kv: (kv[1]["s"], kv[1]["n"], kv[1]["first"]), reverse=True)[:TOP_LIMIT]
    parts.append("\n⭐ <b>Главное за день</b>\n")
    for i, (k, it) in enumerate(top, 1):
        if k in new_keys:
            mark = " · 🆕 в этой сводке"
        elif it.get("urgent"):
            mark = " · ⚡ уже было срочным"
        else:
            mark = f" · ✔ уже было в сводке {it['digest']}" if it.get("digest") else ""
        parts.append(_line(i, it, mark))
    return "\n".join(parts)[:4000]


def process(state, fresh, now, send, total_added=None):
    """Главная точка: учесть свежее, при необходимости отправить срочное и/или сводку.
    send(text) -> bool. Состояние меняется только после успешной отправки. Возвращает state."""
    register(state, fresh, now, total_added)
    items = state["items"]

    # 1) срочное — отдельным сообщением, не чаще раза в час; остальное дождётся сводки
    urgent = [(k, it) for k, it in items.items() if it["s"] >= URGENT_MIN and not it["urgent"] and not it["digest"]]
    if urgent and urgent_allowed(state, now):
        k, it = max(urgent, key=lambda kv: (kv[1]["s"], kv[1]["n"]))
        if send(build_urgent(it, now)):
            it["urgent"] = True
            state["last_urgent_at"] = now.isoformat(timespec="minutes")

    # 2) сводка раз в час
    if digest_due(state, now):
        new_keys = [k for k, it in items.items() if not it["digest"] and not it["urgent"]]
        if not new_keys and not items:
            state["last_digest_at"] = now.isoformat(timespec="minutes")   # пусто — не шумим, слот закрыт
            return state
        if not new_keys:
            state["last_digest_at"] = now.isoformat(timespec="minutes")   # нового важного нет — слот закрыт молча
            return state
        if send(build_digest(state, now, new_keys)):
            for k in new_keys:
                items[k]["digest"] = now.strftime("%H:%M")
            state["last_digest_at"] = now.isoformat(timespec="minutes")
    return state
