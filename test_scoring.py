from scoring import finalize_score, opinion_kind, is_official, rescore_article


def sc(raw, title, n=1, link="https://www.reuters.com/world/x", source="Reuters", summary=""):
    return finalize_score(raw, title, summary, link, source, n)[0]


def test_single_source_never_9_or_10():
    for raw in (8, 9, 10):
        assert sc(raw, "Russia launches missile strike on Ukraine power grid") <= 7


def test_top_scores_are_rare_and_need_confirmation():
    t = "Russia launches missile strike on Ukraine power grid"
    assert sc(10, t, n=2) == 8
    assert sc(10, t, n=3) == 9
    assert sc(10, t, n=4) == 10


def test_opinion_and_column_capped():
    assert sc(10, "Opinion: Trump and Putin are not friends", n=4) <= 5
    assert sc(10, "Trump summit", n=3, link="https://www.theguardian.com/commentisfree/2026/x") <= 5
    assert sc(10, "Колонка: что Россия получит от саммита", n=3) <= 5
    assert opinion_kind("Analysis: why markets fell") == "opinion"


def test_question_essay_lowered():
    # пример из бота: DW «Лопнет ли пузырь ИИ…» получал 10/10
    s = sc(10, "Is the AI bubble about to burst in the U.S. market?", source="DW", link="https://www.dw.com/en/a-1")
    assert s <= 6


def test_minor_diplomatic_news_lowered():
    # пример: посланник Новой Зеландии о связях с Филиппинами получал 8/10
    s = sc(8, "New Zealand envoy talks up ties with the Philippines", source="Rappler", link="https://rappler.com/x")
    assert s <= 4


def test_priority_region_beats_foreign_minor():
    a = sc(9, "Kyiv says Russia struck energy sites overnight", source="Ukrinform", link="https://ukrinform.net/x")
    b = sc(9, "Fiji parliament votes on fishing quota", source="Ukrinform", link="https://ukrinform.net/y")
    assert a > b


def test_official_source_boost_and_confirmation():
    off = sc(8, "Fed holds rates steady", source="FED", link="https://www.federalreserve.gov/newsevents/x")
    non = sc(8, "Fed holds rates steady", source="Blog", link="https://example.com/x")
    assert is_official("https://www.federalreserve.gov/x") and off > non
    assert sc(8, "Iran strikes tanker in Hormuz", n=2) > sc(8, "Iran strikes tanker in Hormuz", n=1)


def test_zero_stays_zero_and_range():
    assert finalize_score(0, "x")[0] == 0
    for raw in range(3, 11):
        for n in (1, 2, 5):
            assert 1 <= sc(raw, "Trump Putin China summit", n=n) <= 10


def test_rescore_keeps_raw_field_and_format():
    a = {"hash": "h", "title": "Putin orders strike on Kyiv", "original_title": "Putin orders strike on Kyiv",
         "link": "https://www.reuters.com/a", "source": "Reuters", "score": 10, "weight": 4, "also": ["BBC"]}
    a["sources_count"] = 2
    rescore_article(a)
    assert a["score_raw"] == 10 and a["score"] == 8 and a["weight"] == 4
