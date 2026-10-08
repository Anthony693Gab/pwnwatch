"""App features: cleanup of old bar integrations, CTF tracking, opportunities, timezone, live events."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

_tmp = tempfile.mkdtemp()
for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
    os.environ.setdefault(var, _tmp)

from pwnwatch import ctf, news, omarchy, server  # noqa: E402
from pwnwatch.config import Config  # noqa: E402
from pwnwatch.fmt import get_tz, when  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_timezone_formatting():
    e = ctf.Event(name="X", start="2026-10-08T12:00:00+00:00", finish="2026-10-09T12:00:00+00:00")
    assert when(e, tz=get_tz("UTC")).startswith("Thu 08 Oct 12:00")
    assert when(e, tz=get_tz("UTC+03:00")).startswith("Thu 08 Oct 15:00")
    assert when(e, tz=get_tz("UTC-05:00")).startswith("Thu 08 Oct 07:00")
    assert get_tz("Not/AZone") is None


def test_week_bounds_follow_timezone():
    # Sunday 23:30 UTC is already Monday in UTC+03:00 → a different week.
    now = datetime(2026, 10, 11, 23, 30, tzinfo=timezone.utc)
    lo_utc, _ = ctf.week_bounds(now, tz=get_tz("UTC"))
    lo_ro, _ = ctf.week_bounds(now, tz=get_tz("UTC+03:00"))
    assert lo_utc.date().isoformat() == "2026-10-05" and lo_ro.date().isoformat() == "2026-10-12"


def test_live_events_close_and_view():
    box = {}
    threading.Thread(target=server.serve, kwargs=dict(
        port=0, offline=True, keep_alive=True, on_ready=lambda p: box.setdefault("p", p)), daemon=True).start()
    while "p" not in box:
        time.sleep(0.05)
    port = box["p"]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{port}"})
    r = c.getresponse()
    assert r.getheader("Content-Type") == "text/event-stream"
    r.fp.readline(); r.fp.readline()  # retry + blank line
    for _ in range(50):
        if server.server_info(port).get("clients"):
            break
        time.sleep(0.05)
    assert server.server_info(port)["clients"] == 1
    server.post_local(port, "/api/view", {"view": "ctf"})
    server.post_local(port, "/api/close", {})
    got = []
    while len(got) < 2:
        line = r.fp.readline().decode().strip()
        if line.startswith("event:"):
            got.append(line.split(":", 1)[1].strip())
    assert got == ["view", "close"]
    c.close()


def test_settings_timezone_validation():
    assert server._clean_settings({"timezone": "UTC+03:00"})["timezone"] == "UTC+03:00"
    assert server._clean_settings({"timezone": "Mars/Base"})["timezone"] == ""
    assert server._clean_settings({"rank_country": "ro"})["rank_country"] == "RO"
    assert server._clean_settings({"rank_country": "xyz"})["rank_country"] == ""



# ---------------------------------------------------------------- cleanup of 0.3 / 0.4 bar integrations


def test_cleanup_removes_every_old_bar_integration(tmp_path):
    cfg = json.loads((FIX / "omarchy-shell.json").read_text())
    before = [e["id"] for e in cfg["bar"]["layout"]["right"]]
    cfg["bar"]["layout"]["right"].insert(0, {"id": "pwnwatch", "type": "command", "exec": "pwnwatch bar"})
    cfg["bar"]["layout"]["right"].insert(1, {"id": "pwnwatch.panel", "bin": "/x/pwnwatch"})
    cfg.setdefault("plugins", []).append({"id": "pwnwatch.panel"})
    shell = tmp_path / "shell.json"
    shell.write_text(json.dumps(cfg))
    (tmp_path / "shell.json.pwnwatch-backup").write_text("{}")
    plugin = tmp_path / "plugins/pwnwatch.panel"
    plugin.mkdir(parents=True)
    (plugin / "Panel.qml").write_text("Item {}")
    hypr = tmp_path / "hypr"
    hypr.mkdir()
    original = (FIX / "hyprland.lua").read_text()
    (hypr / "hyprland.lua").write_text(original.rstrip() + "\n\n" + omarchy.MARK + '\npcall(require, "hypr.pwnwatch")\n')
    (hypr / "pwnwatch.lua").write_text("-- rule")

    msgs = omarchy.cleanup(shell_json=shell, plugin_dir=plugin, hypr_dir=hypr)
    assert len(msgs) == 3
    after = json.loads(shell.read_text())
    assert [e["id"] for e in after["bar"]["layout"]["right"]] == before
    assert all(p.get("id") != "pwnwatch.panel" for p in after.get("plugins", []))
    assert after["bar"]["layout"]["center"][0]["id"] == "omarchy.indicators"
    assert not plugin.exists() and not (hypr / "pwnwatch.lua").exists()
    assert (hypr / "hyprland.lua").read_text().strip() == original.strip()
    assert not (tmp_path / "shell.json.pwnwatch-backup").exists()
    assert omarchy.cleanup(shell_json=shell, plugin_dir=plugin, hypr_dir=hypr) == []  # idempotent


def test_cleanup_leaves_untouched_config_alone(tmp_path):
    shell = tmp_path / "shell.json"
    text = (FIX / "omarchy-shell.json").read_text()
    shell.write_text(text)
    assert omarchy.cleanup(shell_json=shell, plugin_dir=tmp_path / "none", hypr_dir=tmp_path) == []
    assert shell.read_text() == text


# ---------------------------------------------------------------- CTF tracking (mine / past / history)


def _hub_with_events(now):
    items = [
        {"id": 101, "title": "Running CTF", "start": (now - timedelta(hours=12)).isoformat(),
         "finish": (now + timedelta(hours=36)).isoformat(), "onsite": False, "weight": 40},
        {"id": 102, "title": "Finished Onsite", "start": (now - timedelta(days=5)).isoformat(),
         "finish": (now - timedelta(days=5) + timedelta(hours=8)).isoformat(), "onsite": True,
         "location": "Bucharest, Romania", "weight": 25},
        {"id": 103, "title": "Next Week CTF", "start": (now + timedelta(days=8)).isoformat(),
         "finish": (now + timedelta(days=10)).isoformat(), "onsite": False},
    ]
    from dataclasses import asdict
    evs = ctf.parse_ctftime(items, {})
    write_json(cache_path("ctf.json"), {"fetched": now.isoformat(), "events": [asdict(e) for e in evs]})
    write_json(cache_path("team.json"), {"team": {"id": 9, "name": "T", "country": "RO"},
                                         "results": [{"event_id": 102, "title": "Finished Onsite",
                                                      "place": 7, "points": 900.0, "teams": 120}]})
    return server.Hub(offline=True)


from pwnwatch.store import cache_path, state_path, write_json  # noqa: E402


def test_event_ids_use_ctftime_ids_and_durations():
    now = datetime.now(timezone.utc)
    hub = _hub_with_events(now)
    st = hub.state()
    ev = {e["name"]: e for e in st["events"]}
    assert ev["Running CTF"]["id"] == "ct101"
    assert ev["Running CTF"]["live"] and ev["Running CTF"]["duration"] == "48h"
    assert 0.2 < ev["Running CTF"]["progress"] < 0.3
    assert ev["Finished Onsite"]["past"] and ev["Finished Onsite"]["section"] == "past"
    assert ev["Finished Onsite"]["duration"] == "8h"
    assert ev["Next Week CTF"]["duration"] == "48h" and not ev["Next Week CTF"]["past"]
    dc = next(e for e in st["events"] if e["name"] == "DEF CON 35")
    assert dc["duration"] == "4 days"
    bd = next(e for e in st["events"] if e["name"].startswith("Bitdefender"))
    assert bd["start"].startswith("2026-11-12") and bd["duration"] == "1 day"
    assert any(e["name"].startswith("Olimpiada de Securitate") and e["section"] == "tba" for e in st["events"])


def test_save_register_and_history():
    now = datetime.now(timezone.utc)
    hub = _hub_with_events(now)
    assert hub.set_mine("ct103", status="saved")
    assert hub.set_mine("ct102", status="registered")
    assert not hub.set_mine("nope", status="saved")
    st = hub.state()
    ev = {e["id"]: e for e in st["events"]}
    assert ev["ct103"]["mine"] == "saved"
    past = ev["ct102"]
    assert past["mine"] == "registered" and past["place"] == 7 and past["teams"] == 120
    assert past["result_source"] == "ctftime"
    hs = st["history"]
    assert hs["played"] == 1 and hs["onsite"] == 1 and hs["best"] == 7 and hs["countries"] == ["RO"]
    assert hs["cities"] == ["Bucharest"] and hs["hours"] == 8

    hub.set_mine("ct102", notes="solved 4 web", place="#3", teams="120")
    rec = json.loads(state_path("mine.json").read_text())["ct102"]
    assert rec["notes"] == "solved 4 web" and rec["place"] == 3 and rec["event"]["name"] == "Finished Onsite"
    assert hub.state()["history"]["best"] == 3

    # the event survives after CTFtime stops listing it
    hub.events = [e for e in hub.events if e.id != "ct102"]
    assert any(e["id"] == "ct102" and e["mine"] == "registered" for e in hub.state()["events"])
    hub.set_mine("ct102", status="none")
    assert "ct102" not in json.loads(state_path("mine.json").read_text())


def test_new_on_ctftime_shows_in_news_opportunities():
    now = datetime.now(timezone.utc)
    hub = _hub_with_events(now)
    # first run marks everything as old
    ctf.note_first_seen(hub.events)
    assert not [i for i in hub.state()["news"] if i["id"].startswith("op-ct")]
    # a new event appears on a later refresh
    new = ctf.parse_ctftime([{"id": 555, "title": "Brand New CTF", "url": "https://new.ctf/",
                              "ctftime_url": "https://ctftime.org/event/555/",
                              "start": (now + timedelta(days=3)).isoformat(),
                              "finish": (now + timedelta(days=4)).isoformat(), "onsite": False}])[0]
    ctf.note_first_seen(hub.events + [new])
    hub.events = hub.events + [new]
    news_items = hub.state()["news"]
    op = next(i for i in news_items if i["id"] == "op-ct555")
    assert op["title"] == "New on CTFtime: Brand New CTF" and op["opportunity"] and op["unread"]
    assert "24h" in op["summary"]
    hub.mark_read(["op-ct555"])
    assert not next(i for i in hub.state()["news"] if i["id"] == "op-ct555")["unread"]
    # hand-picked events within 45 days show as "Coming up"
    assert any(i["title"].startswith("Coming up: Bitdefender") for i in news_items) == (
        datetime(2026, 11, 12, 9, tzinfo=timezone.utc) - now <= timedelta(days=45))


def test_google_news_opportunity_feed_parsing():
    rss = b"""<rss><channel><item>
      <title>Bitdefender launches student CTF with DEF CON prize - Profit.ro</title>
      <link>https://news.google.com/rss/articles/abc</link>
      <pubDate>Wed, 07 Oct 2026 08:00:00 GMT</pubDate>
      <description>&lt;a href="x"&gt;Bitdefender launches student CTF&lt;/a&gt;&amp;nbsp;&amp;nbsp;Profit.ro</description>
      <source url="https://www.profit.ro">Profit.ro</source>
    </item></channel></rss>"""
    a = news.parse_feed("Opportunities: x", rss)[0]
    assert a.title == "Bitdefender launches student CTF with DEF CON prize"
    assert a.publisher == "Profit.ro"
    tagged = news.tag_article(a, ["Bitdefender"])
    assert "OPPORTUNITY" in tagged.tags and tagged.watch
    feeds = news.opportunity_feeds(Config())
    assert len(feeds) == 4 and all("news.google.com/rss/search" in u for u in feeds.values())
    ro = [u for u in feeds.values() if "gl=RO" in u]
    assert len(ro) == 1 and "hl=ro" in ro[0]


def test_custom_feed_from_settings_is_fetched(monkeypatch):
    from pwnwatch.config import active_feeds, load_config, write_settings
    write_settings({"extra_feeds": {"My Blog": "https://blog.example/feed.xml"}, "disabled_feeds": ["Dark Reading"]})
    cfg = load_config()
    feeds = active_feeds(cfg)
    assert feeds["My Blog"] == "https://blog.example/feed.xml" and "Dark Reading" not in feeds
    rss = b"""<rss xmlns:media="http://search.yahoo.com/mrss/"><channel><item><title>Hello</title>
      <link>https://blog.example/p/1</link><media:content url="https://blog.example/i.jpg" medium="image"/>
      </item></channel></rss>"""
    calls = []
    def fake_get(url, timeout=15.0):
        calls.append(url)
        if url == "https://blog.example/feed.xml":
            return rss
        raise OSError("offline")
    monkeypatch.setattr(news, "http_get", fake_get)
    arts, errs = news.fetch_all(cfg)
    mine = [a for a in arts if a.source == "My Blog"]
    assert mine and mine[0].image == "https://blog.example/i.jpg"  # same thumbnail path as built-in feeds
    write_settings({"extra_feeds": {}, "disabled_feeds": []})
