"""Command-line entry point.

    pwnwatch            open the app window (starts the local backend if needed)
    pwnwatch serve      run the backend in the foreground
    pwnwatch stop       stop a running backend
    pwnwatch toggle     open the window, or close it if it is open
    pwnwatch cleanup    remove the bar icon/panel older versions added
    pwnwatch digest     send the daily desktop notification
    pwnwatch week|news  plain-text output for scripts
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from . import __version__


def _ensure_backend(offline: bool) -> int:
    from .server import log_file, running_port

    port = running_port()
    if port:
        return port
    cmd = [sys.executable, "-m", "pwnwatch", "serve"] + (["--offline"] if offline else [])
    with open(log_file(), "a") as log:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)
    for _ in range(60):
        time.sleep(0.15)
        port = running_port()
        if port:
            return port
    raise SystemExit("pwnwatch: the backend did not start (try `pwnwatch serve` to see why)")


def _mark(args) -> int:
    """read/save go through the running backend when there is one, so both stay in sync."""
    from .server import post_local, running_port

    port = running_port()
    if args.cmd == "read":
        body = {"all": True} if args.all else {"ids": args.ids}
        if port:
            post_local(port, "/api/read", body)
            return 0
        from . import news
        from .store import SeenSet

        arts, _ = news.load_cache()
        SeenSet().add_many(a.link for a in arts if args.all or a.id in args.ids)
        return 0
    body = {"id": args.id, "saved": not args.remove}
    if port:
        post_local(port, "/api/save", body)
        return 0
    from .server import Hub

    Hub(offline=True).set_saved(args.id, not args.remove)
    return 0


def _toggle(args) -> int:
    """Open the window, or close it if it is already open (handy for a keybinding)."""
    from .server import launch_window, post_local, running_port, server_info

    port = running_port()
    info = server_info(port) if port else None
    if info and info.get("clients"):
        post_local(port, "/api/view" if args.view else "/api/close", {"view": args.view} if args.view else {})
        return 0
    port = _ensure_backend(args.offline)
    launch_window(f"http://127.0.0.1:{port}/" + (f"#{args.view}" if args.view else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pwnwatch",
                                description="Cybersecurity news and CTF radar, themed by Omarchy.")
    p.add_argument("--version", action="version", version=f"pwnwatch {__version__}")
    p.add_argument("--offline", action="store_true", help="use cached data only")
    p.add_argument("--no-window", action="store_true", help="start the backend and print the URL")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the backend in the foreground")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--offline", action="store_true")
    s.add_argument("--keep-alive", action="store_true", help="don't exit when the window closes")
    sub.add_parser("stop", help="stop the backend")
    d = sub.add_parser("digest", help="send today's digest as a desktop notification")
    d.add_argument("--print", action="store_true", help="print to stdout instead of notifying")
    sub.add_parser("week", help="print this week's CTFs")
    t = sub.add_parser("toggle", help="open the window, or close it if it is open")
    t.add_argument("--view", choices=["news", "ctf", "team"])
    sub.add_parser("json", help="news + CTF snapshot as JSON (what the Omarchy panel reads)")
    rd = sub.add_parser("read", help="mark stories read")
    rd.add_argument("ids", nargs="*")
    rd.add_argument("--all", action="store_true")
    sv = sub.add_parser("save", help="save (or --remove) a story")
    sv.add_argument("id")
    sv.add_argument("--remove", action="store_true")
    rk = sub.add_parser("rank", help="pick the country for the team leaderboard")
    rk.add_argument("country")
    sub.add_parser("refresh", help="fetch news and CTFs now")
    sub.add_parser("cleanup", help="remove the bar icon/panel that older versions added")
    sub.add_parser("news", help="print the latest headlines")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        from .server import DEFAULT_PORT, serve

        def ready(port: int) -> None:
            print(f"pwnwatch backend on http://127.0.0.1:{port}/", flush=True)

        serve(args.port or DEFAULT_PORT, offline=args.offline, keep_alive=args.keep_alive, on_ready=ready)
        return 0

    if args.cmd == "stop":
        from .server import RUNTIME, running_port
        from .store import read_json

        if running_port():
            pid = read_json(RUNTIME, {}).get("pid")
            if pid:
                os.kill(int(pid), signal.SIGTERM)
                print("stopped")
        return 0

    from .config import load_config

    if args.cmd == "json":
        import json

        from .omarchy import maybe_refresh_in_background
        from .snapshot import snapshot

        cfg = load_config()
        snap = snapshot(cfg)
        print(json.dumps(snap, ensure_ascii=False, default=str))
        from datetime import datetime

        maybe_refresh_in_background(datetime.fromisoformat(snap["updated"]) if snap["updated"] else None)
        return 0

    if args.cmd in ("read", "save"):
        return _mark(args)

    if args.cmd == "rank":
        from . import ctf
        from .config import write_settings

        cc = args.country.strip().upper()
        if len(cc) != 2 or not cc.isalpha():
            raise SystemExit("pwnwatch: use a 2-letter country code, e.g. RO")
        write_settings({"rank_country": cc})
        rows, err = ctf.fetch_top_country(cc)
        print(f"{len(rows)} ranked teams in {cc}" + (f" ({err})" if err else ""))
        return 0

    if args.cmd == "refresh":
        from .omarchy import refresh_caches

        refresh_caches(load_config())
        return 0

    if args.cmd == "cleanup":
        from .omarchy import cleanup

        msgs = cleanup()
        for m in msgs:
            print("pwnwatch:", m)
        if not msgs:
            print("pwnwatch: nothing to clean up")
        return 0

    if args.cmd == "toggle":
        try:
            return _toggle(args)
        except Exception as exc:  # usually run from a keybinding; leave a trace
            from .server import log_file

            with open(log_file(), "a") as fh:
                fh.write(f"{time.strftime('%F %T')} toggle failed: {exc!r}\n")
            raise

    if args.cmd == "digest":
        from . import digest

        return digest.run(load_config(), print_only=args.print)

    if args.cmd == "week":
        from . import ctf
        from .fmt import country_cell, when

        events, err = ctf.fetch_all(load_config())
        lo, hi = ctf.week_bounds()
        for e in (e for e in events if ctf.overlaps(e, lo, hi)):
            w = f"{e.weight:5.1f}" if e.weight is not None else "    —"
            print(f"{when(e):28} {e.mode:7} {w}  {country_cell(e):4}  {e.name}  {e.url}")
        if err:
            print(err, file=sys.stderr)
        return 0

    if args.cmd == "news":
        from . import news
        from .fmt import age

        arts, errs = news.fetch_all(load_config())
        for a in arts[:40]:
            print(f"{age(a.dt):>5}  {a.source[:16]:16}  {a.title}")
        for k, v in errs.items():
            print(f"! {k}: {v}", file=sys.stderr)
        return 0

    from .server import launch_window, server_info

    port = _ensure_backend(args.offline)
    url = f"http://127.0.0.1:{port}/"
    if args.no_window:
        print(url)
    elif (server_info(port) or {}).get("clients"):
        from .server import focus_window

        if not focus_window():
            print("pwnwatch is already open")
    else:
        launch_window(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
