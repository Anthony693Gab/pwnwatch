"""Backend tests: run the real HTTP server on a random port, offline."""

from __future__ import annotations

import http.client
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp()
for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
    os.environ.setdefault(var, _tmp)

from pwnwatch import ctf, news, server, theme  # noqa: E402
from pwnwatch.config import CACHE_DIR, Config  # noqa: E402
from pwnwatch.store import write_json  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    tdir = tmp_path_factory.mktemp("theme")
    (tdir / "colors.toml").write_text('accent = "#7aa2f7"\nbackground = "#1a1b26"\nforeground = "#a9b1d6"\n')
    theme.THEME_DIRS = [tdir]

    arts = news.finalize([news.Article(title="Test story about ransomware", link="https://example.com/s1",
                                       source="Test", published=NOW.isoformat())], Config())
    news.save_cache(arts)
    ev = ctf.parse_ctftime([{
        "id": 1, "title": "Test CTF", "url": "https://ctf.example/", "ctftime_url": "https://ctftime.org/event/1/",
        "start": (NOW + timedelta(days=1)).isoformat(), "finish": (NOW + timedelta(days=2)).isoformat(),
        "onsite": False, "location": "", "weight": 30, "format": "Jeopardy", "organizers": [],
    }])
    write_json(CACHE_DIR / "ctf.json", {"fetched": NOW.isoformat(), "events": [asdict(e) for e in ev]})

    box = {}
    t = threading.Thread(target=server.serve, kwargs=dict(
        port=0, offline=True, keep_alive=True, on_ready=lambda p: box.setdefault("port", p)), daemon=True)
    t.start()
    for _ in range(100):
        if "port" in box:
            break
        time.sleep(0.05)
    return {"port": box["port"], "theme": tdir}


def req(srv, method, path, body=None, host="127.0.0.1", ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", srv["port"], timeout=5)
    headers = {"Host": f"{host}:{srv['port']}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode() if ctype == "application/json" else body
        headers["Content-Type"] = ctype
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    return r.status, r.read(), dict(r.getheaders())


def test_ping_and_state(srv):
    code, body, _ = req(srv, "GET", "/api/ping")
    assert code == 200 and json.loads(body)["app"] == "pwnwatch"
    code, body, _ = req(srv, "GET", "/api/state")
    st = json.loads(body)
    assert st["news"][0]["title"].startswith("Test story") and st["news"][0]["unread"]
    assert any(e["name"] == "Test CTF" and e["section"] in ("week", "soon") for e in st["events"])
    assert any(e["name"] == "DEF CON 35" for e in st["events"])


def test_static_and_csp(srv):
    code, body, hdrs = req(srv, "GET", "/")
    assert code == 200 and b"<title>pwnwatch</title>" in body
    assert "script-src 'self'" in hdrs["Content-Security-Policy"]
    code, _, _ = req(srv, "GET", "/static/../server.py")
    assert code == 404


def test_rejects_foreign_host(srv):
    code, _, _ = req(srv, "GET", "/api/state", host="evil.example")
    assert code == 403


def test_post_requires_json(srv):
    code, _, _ = req(srv, "POST", "/api/refresh", body=b"x=1", ctype="application/x-www-form-urlencoded")
    assert code == 400


def test_open_only_known_urls(srv):
    code, _, _ = req(srv, "POST", "/api/open", {"url": "file:///etc/passwd"})
    assert code == 400
    code, _, _ = req(srv, "POST", "/api/open", {"url": "https://unknown.example/"})
    assert code == 400


def test_settings_team_url_and_read_state(srv):
    code, body, _ = req(srv, "POST", "/api/settings",
                        {"team_id": "https://ctftime.org/team/31337", "home_country": "ro",
                         "watch_words": ["Romania"], "big_weight": "60"})
    assert code == 200
    st = json.loads(req(srv, "GET", "/api/state")[1])
    assert st["settings"]["team_id"] == 31337 and st["settings"]["big_weight"] == 60
    aid = st["news"][0]["id"]
    req(srv, "POST", "/api/read", {"ids": [aid]})
    req(srv, "POST", "/api/save", {"id": aid, "saved": True})
    st = json.loads(req(srv, "GET", "/api/state")[1])
    assert not st["news"][0]["unread"] and st["news"][0]["saved"]


def test_ics(srv):
    st = json.loads(req(srv, "GET", "/api/state")[1])
    eid = next(e["id"] for e in st["events"] if e["name"] == "Test CTF")
    code, body, hdrs = req(srv, "GET", f"/api/ics/{eid}")
    assert code == 200 and b"BEGIN:VCALENDAR" in body and b"SUMMARY:Test CTF" in body
    assert hdrs["Content-Type"] == "text/calendar"


def test_theme_follows_omarchy(srv):
    fp1 = json.loads(req(srv, "GET", "/api/theme")[1])["fp"]
    css = req(srv, "GET", "/theme.css")[1].decode()
    assert "--accent: #7aa2f7" in css and "--background: #1a1b26" in css
    (srv["theme"] / "colors.toml").write_text('accent = "#e68e0d"\nbackground = "#121212"\nforeground = "#bebebe"\n')
    fp2 = json.loads(req(srv, "GET", "/api/theme")[1])["fp"]
    assert fp1 != fp2 and "--accent: #e68e0d" in req(srv, "GET", "/theme.css")[1].decode()


def test_light_theme_detected(tmp_path):
    (tmp_path / "colors.toml").write_text('background = "#eff1f5"\nforeground = "#4c4f69"\n')
    old = theme.THEME_DIRS
    theme.THEME_DIRS = [tmp_path]
    try:
        assert theme.load_palette()["mode"] == "light"
    finally:
        theme.THEME_DIRS = old


def test_legacy_alacritty_theme(tmp_path):
    (tmp_path / "alacritty.toml").write_text(
        '[colors.primary]\nbackground = "0x1e1e2e"\nforeground = "#cdd6f4"\n'
        '[colors.normal]\nred = "#f38ba8"\nblue = "#89b4fa"\n')
    old = theme.THEME_DIRS
    theme.THEME_DIRS = [tmp_path]
    try:
        p = theme.load_palette()
        assert p["background"] == "#1e1e2e" and p["accent"] == "#89b4fa" and p["red"] == "#f38ba8"
    finally:
        theme.THEME_DIRS = old


def test_image_fetch_refuses_private_addresses():
    for url in ("http://127.0.0.1/x.png", "http://localhost/x.png", "http://10.0.0.1/x.png",
                "http://169.254.169.254/latest", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            server.safe_fetch(url, limit=100)


def test_feed_thumbnails():
    rss = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
    <item><title>A</title><link>https://x.example/a</link><media:thumbnail url="https://cdn.example/a.jpg"/></item>
    <item><title>B</title><link>https://x.example/b</link><enclosure url="https://cdn.example/b.png" type="image/png"/></item>
    <item><title>C</title><link>https://x.example/c</link>
      <description><![CDATA[<img src="https://feeds.feedburner.com/~r/x" width="1"><img src="/img/c.jpg">]]></description></item>
    </channel></rss>"""
    a, b, c = news.parse_feed("T", rss)
    assert a.image == "https://cdn.example/a.jpg"
    assert b.image == "https://cdn.example/b.png"
    assert c.image == "https://x.example/img/c.jpg"


def test_team_parsers():
    t = ctf.parse_team({"id": 5, "name": "X", "country": "ro",
                        "rating": {"2026": {"rating_place": 10, "rating_points": 99.5, "country_place": 2}}}, 2026)
    assert t["place"] == 10 and t["country"] == "RO" and t["url"].endswith("/team/5")
    res = ctf.parse_results({"77": {"title": "E", "time": 5, "scores": [
        {"team_id": 1, "points": "10", "place": 1}, {"team_id": 5, "points": "5", "place": 2}]}}, 5)
    assert res[0]["place"] == 2 and res[0]["teams"] == 2
    top = ctf.parse_top_country({"RO": [{"team_id": 5, "team_name": "X", "points": 99.5, "place": 10, "country_place": 2}]}, "RO")
    assert top[0]["name"] == "X"
