from datetime import date
from types import SimpleNamespace

import pytest

from src.alerts import triage
from src.alerts.notify import build_digest, split_message
from src.alerts.triage import EXPLAINED, UNCLEAR, UNEXPLAINED, parse_reply, rule_triage, triage_alert


def _alert(**kw):
    a = {"alert_id": "a1", "trade_date": date(2026, 10, 6), "symbol": "TEST", "company_name": "Test Ltd",
         "risk_score": 73.0, "risk_band": "HIGH", "rules_triggered": "VOLUME_SPIKE, PRICE_SHOCK",
         "reason": "Volume 10.0x its 20-day average", "news_types": None, "exchange_query": False}
    a.update(kw)
    return a


def test_rule_triage_no_news_is_worth_a_look():
    t = rule_triage(None, False)
    assert t.verdict == UNEXPLAINED and "worth a look" in t.line


def test_rule_triage_exchange_query_without_news():
    assert "NSE has asked" in rule_triage(None, True).line


def test_rule_triage_with_news_is_unclear():
    t = rule_triage("ORDER_WIN, RESULTS", False)
    assert t.verdict == UNCLEAR and "order win, results" in t.line


def test_parse_reply_accepts_fenced_json():
    assert parse_reply('```json\n{"verdict": "explained", "line": "Q2 results"}\n```') == (EXPLAINED, "Q2 results")


def test_parse_reply_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        parse_reply('{"verdict": "MAYBE", "line": "x"}')


def test_no_news_skips_llm(monkeypatch):
    called = []
    monkeypatch.setitem(triage.PROVIDERS, "gemini", (lambda *a: called.append(1), "GEMINI_API_KEY"))
    t = triage_alert(con=None, alert=_alert(), cfg=("gemini", "m", "k"))
    assert t.source == "rules" and not called


def test_llm_failure_falls_back_to_rules(monkeypatch):
    def boom(*a):
        raise RuntimeError("429 rate limited")
    monkeypatch.setitem(triage.PROVIDERS, "gemini", (boom, "GEMINI_API_KEY"))
    monkeypatch.setattr(triage, "_filings", lambda con, s, d: [])
    t = triage_alert(con=None, alert=_alert(news_types="RESULTS"), cfg=("gemini", "m", "k"))
    assert t.source == "rules" and t.verdict == UNCLEAR


def test_llm_reply_is_used(monkeypatch):
    monkeypatch.setitem(triage.PROVIDERS, "gemini",
                        (lambda p, m, k: '{"verdict": "EXPLAINED", "line": "Explained: Q2 results"}', "X"))
    monkeypatch.setattr(triage, "_filings", lambda con, s, d: [])
    t = triage_alert(con=None, alert=_alert(news_types="RESULTS"), cfg=("gemini", "gm", "k"))
    assert (t.verdict, t.line, t.source) == (EXPLAINED, "Explained: Q2 results", "llm:gm")


def test_digest_skips_recent_medium_names_and_shows_triage():
    alerts = [_alert(triage="No company news in the last 3 days: worth a look", verdict=UNEXPLAINED),
              _alert(alert_id="a2", symbol="OLD", risk_band="MEDIUM", risk_score=50.0),
              _alert(alert_id="a3", symbol="NEW", risk_band="MEDIUM", risk_score=45.0, news_types="RESULTS")]
    dq = [SimpleNamespace(check="freshness", status="PASS")]
    text = build_digest(date(2026, 10, 6), alerts, dq, seen={"OLD"})
    assert "🔎 No company news" in text
    assert "• NEW (45)" in text and "news: results" in text
    assert "OLD" not in text
    assert "all checks passed" in text


def test_digest_does_not_claim_quality_when_checks_skipped():
    assert "not checked in this run" in build_digest(date(2026, 10, 6), [], [], seen=set())


def test_split_message_keeps_lines_whole():
    text = "".join(f"line {i:03d}\n" for i in range(100))
    chunks = split_message(text, limit=50)
    assert "".join(chunks) == text and all(len(c) <= 50 for c in chunks)
