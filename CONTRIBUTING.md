# Contributing

- **Event dates** are the easiest and most useful PR: edit `src/pwnwatch/events.py`
  (DefCamp, Bitdefender's CTF, OSC, UNbreakable, RoCSC, ECSC, events from your country).
  Add a link to the organiser's announcement in the PR.
- **Feeds**: suggest good English-language security feeds in an issue.
- **Code**: `pip install -e '.[dev]' && pytest`, then `pwnwatch serve --keep-alive` and open
  http://127.0.0.1:47431/. The UI is plain HTML/CSS/JS in `src/pwnwatch/web/` — no build step.
  Never insert feed text with `innerHTML`.
