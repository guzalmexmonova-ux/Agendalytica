from datetime import datetime, timedelta, timezone

import digest

TZ = timezone(timedelta(hours=5))


def art(h, score, title="Putin signs decree on energy exports to Europe", src="Reuters", n=1):
    return {"hash": h, "title": title, "original_title": title, "link": f"https://x/{h}", "source": src,
            "score": score, "score_raw": 10, "sources_count": n}


def at(h, m=0, d=19):
    return datetime(2026, 11, d, h, m, tzinfo=TZ)


def test_slot_schedule():
    st = digest.new_state("2026-11-19")
    assert digest.digest_due(st, at(10))                       # первый запуск
    st["last_digest_at"] = at(9, 5).isoformat()
    assert not digest.digest_due(st, at(10, 50))               # тот же слот 9–12
    assert digest.digest_due(st, at(12, 0))                    # новый слот
    assert digest.slot_start(at(14, 30)).hour == 12


def test_digest_once_per_3h_with_15min_cron():
    sent, st = [], digest.new_state("2026-11-19")
    k = 0
    t = at(0, 0)
    while t < at(23, 59):
        k += 1
        st = digest.load_state(st, t)
        digest.process(st, [art(f"h{k}", 7, f"Story number {k} about Russia and Ukraine talks")], t,
                       lambda x: sent.append(x) or True)
        t += timedelta(minutes=15)
    digests = [s for s in sent if s.startswith("🗓")]
    assert len(digests) == 8                                    # 24ч / 3ч, а не 96 сообщений
    assert all("важных" in d and "всего" in d for d in digests)


def test_no_new_important_means_silence():
    sent, st = [], digest.new_state("2026-11-19")
    digest.process(st, [art("a", 5)], at(9, 1), lambda x: sent.append(x) or True)
    assert sent == [] and st["total"] == 1 and st["items"] == {}


def test_digest_marks_already_sent_and_counts():
    sent, st = [], digest.new_state("2026-11-19")
    digest.process(st, [art("a", 8, "Alpha story Iran Hormuz tanker attack")], at(9, 1), lambda x: sent.append(x) or True)
    digest.process(st, [art("b", 7, "Beta story China Taiwan drills")], at(12, 2), lambda x: sent.append(x) or True)
    txt = sent[-1]
    assert "1 важных" not in txt and "2 важных / 2 всего" in txt
    assert "уже было в сводке 09:01" in txt and "в этой сводке" in txt


def test_urgent_immediately_but_once_per_hour():
    sent, st = [], digest.new_state("2026-11-19")
    send = lambda x: sent.append(x) or True
    digest.process(st, [art("u1", 9, "Nuclear alert one")], at(10, 0), send)
    digest.process(st, [art("u2", 10, "Coup attempt two")], at(10, 20), send)
    urgent = [s for s in sent if s.startswith("🚨")]
    assert len(urgent) == 1                                     # второе — ждёт час
    digest.process(st, [], at(11, 5), send)
    assert len([s for s in sent if s.startswith("🚨")]) == 2
    # срочное не дублируется в «Новое» сводки
    digest.process(st, [], at(12, 1), send)
    assert "Nuclear alert one" not in sent[-1].split("Главное за день")[0]


def test_failed_send_keeps_items_pending():
    st = digest.new_state("2026-11-19")
    digest.process(st, [art("a", 8)], at(9, 1), lambda x: False)
    assert st["last_digest_at"] == "" and st["items"]["a"]["digest"] == ""
    sent = []
    digest.process(st, [], at(9, 16), lambda x: sent.append(x) or True)
    assert len(sent) == 1


def test_new_day_resets_counters_not_clock():
    st = digest.new_state("2026-11-19"); st["total"] = 50; st["last_digest_at"] = at(21, 5).isoformat()
    st2 = digest.load_state(st, at(0, 10, d=20))
    assert st2["total"] == 0 and st2["items"] == {} and st2["last_digest_at"] == st["last_digest_at"]


def test_bump_rescores_on_confirmation():
    st = digest.new_state("2026-11-19")
    digest.register(st, [art("a", 7, "Russia hits Kyiv energy grid with missiles")], at(10))
    for src in ("BBC", "AP News", "FT"):
        assert digest.bump(st, {"title": "Russia hits Kyiv energy grid with missiles overnight", "source": src})
    it = st["items"]["a"]
    assert it["n"] == 4 and it["s"] >= 9
