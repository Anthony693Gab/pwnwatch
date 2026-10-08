/* pwnwatch UI — no framework, no build step. Remote text always goes through
   textContent (never innerHTML), so feed content can't inject markup. */
"use strict";

// ---------------------------------------------------------------- icons (static, trusted)
const ICON = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 3v5h5"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/><path d="M20 21v-5h-5"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.4 13a7.6 7.6 0 0 0 0-2l2.1-1.6a.5.5 0 0 0 .1-.6l-2-3.5a.5.5 0 0 0-.6-.2l-2.5 1a7.4 7.4 0 0 0-1.7-1L14.4 2.4a.5.5 0 0 0-.5-.4h-4a.5.5 0 0 0-.5.4L9 5.1a7.6 7.6 0 0 0-1.7 1l-2.5-1a.5.5 0 0 0-.6.2l-2 3.5a.5.5 0 0 0 .1.6L4.6 11a7.6 7.6 0 0 0 0 2l-2.1 1.6a.5.5 0 0 0-.1.6l2 3.5c.1.2.4.3.6.2l2.5-1c.5.4 1.1.7 1.7 1l.4 2.7c0 .2.3.4.5.4h4c.2 0 .5-.2.5-.4l.4-2.7c.6-.3 1.2-.6 1.7-1l2.5 1c.2.1.5 0 .6-.2l2-3.5a.5.5 0 0 0-.1-.6zM12 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>',
  bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>',
  flag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 21V4"/><path d="M5 4h12l-2 4 2 4H5"/></svg>',
  cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12.5 9.5 18 20 6.5"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
};

// ---------------------------------------------------------------- tiny DOM helper
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v; // only ever used with ICON strings
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false || kid === "") continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (s) => document.querySelector(s);
const dot = () => h("span", { class: "sep" }, "·");

// ---------------------------------------------------------------- state
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem("pw:" + k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("pw:" + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const S = {
  data: null,
  raw: "",
  view: store.get("view", "news"),
  chip: store.get("chip", { news: "all", ctf: "upcoming" }),
  country: store.get("country", ""),
  source: "",
  mode: store.get("mode", "any"),
  q: "",
  sel: { news: null, ctf: null },
  items: [],
  objs: new Map(),
  themeFp: null,
  top: null, // leaderboard for the team view: {country, rows}
};

// ---------------------------------------------------------------- api
async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

async function load(force) {
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    const text = await r.text();
    if (!force && text === S.raw) { renderFooter(); return; }
    S.raw = text;
    S.data = JSON.parse(text);
    render();
  } catch {
    $("#foot-right").textContent = "backend offline — run pwnwatch again";
  }
}

// Live updates: the backend pushes 'state', 'close' and 'view'. The open
// connection is also what keeps the backend alive while the window is open.
function listen() {
  const es = new EventSource("/api/events");
  es.addEventListener("state", () => load());
  es.addEventListener("close", () => window.close());
  es.addEventListener("view", (e) => {
    const v = JSON.parse(e.data);
    if (v === "team") { S.view = "ctf"; S.chip.ctf = "team"; render(); } else setView(v);
  });
  es.onerror = () => { /* EventSource reconnects by itself */ };
}

async function watchTheme() {
  try {
    const { fp } = await api("/api/theme");
    if (S.themeFp && fp !== S.themeFp) $("#theme-css").href = "/theme.css?v=" + fp;
    S.themeFp = fp;
  } catch { /* backend restarting */ }
  setTimeout(watchTheme, 2500);
}

// ---------------------------------------------------------------- time helpers
function ago(iso) {
  if (!iso) return "";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  if (s < 7 * 86400) return Math.floor(s / 86400) + "d";
  return new Date(iso).toLocaleDateString("en-GB", { month: "short", day: "numeric" });
}
function dayLabel(iso) {
  if (!iso) return "Earlier";
  const d = new Date(iso), t = new Date();
  const days = Math.round((new Date(t.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "short" });
}
function mb(n) { return n > 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.round(n / 1e3) + " KB"; }

// UTC offsets for the time-zone picker ("" = system time).
const TZS = (() => {
  const out = [["", "Local time"], ["UTC", "UTC"]];
  const offs = [-12, -11, -10, -9, -8, -7, -6, -5, -4, -3, -2, -1, 1, 2, 3, 3.5, 4, 5, 5.5, 5.75, 6, 7, 8, 9, 9.5, 10, 11, 12, 13, 14];
  for (const o of offs) {
    const sign = o < 0 ? "-" : "+", a = Math.abs(o);
    const v = `UTC${sign}${String(Math.floor(a)).padStart(2, "0")}:${String(Math.round((a % 1) * 60)).padStart(2, "0")}`;
    out.push([v, v.replace("-", "−")]);
  }
  return out;
})();

// ---------------------------------------------------------------- filters
const TAG_HUE = { "0DAY": "--red", RANSOM: "--red", BREACH: "--yellow", MALWARE: "--yellow",
  ARREST: "--green", APT: "--magenta", CVE: "--cyan", PHISH: "--blue", AI: "--blue", OPPORTUNITY: "--green" };

const newsItems = () => S.data?.news || [];
const events = () => S.data?.events || [];
const upcoming = (e) => !e.past && e.section !== "tba";

function chipsFor(view) {
  if (view === "news") {
    const live = newsItems().filter((a) => !a.archived);
    const c = [
      { id: "all", label: "All", n: live.length },
      { id: "unread", label: "Unread", n: live.filter((a) => a.unread).length },
    ];
    const w = live.filter((a) => a.watch).length;
    if (w) c.push({ id: "watch", label: "★", n: w, title: "Mentions your watch words" });
    c.push({ id: "opps", label: "Opportunities", n: live.filter((a) => a.opportunity).length,
      title: "Competitions, CTFs, scholarships and new events — even ones the news sites skip" });
    const saved = newsItems().filter((a) => a.saved).length;
    if (saved) c.push({ id: "saved", label: "Saved", n: saved });
    return c;
  }
  const ev = events();
  const live = ev.filter((e) => e.live).length;
  return [
    { id: "upcoming", label: "Upcoming", n: ev.filter(upcoming).length },
    { id: "live", label: "Live", n: live, cls: live ? "live" : "" },
    { id: "mine", label: "Mine", n: ev.filter((e) => e.mine && !e.past).length,
      title: "CTFs you saved or registered for" },
    { id: "tba", label: "Watchlist", n: ev.filter((e) => e.section === "tba").length },
    { id: "past", label: "Past", n: ev.filter((e) => e.past).length },
    { id: "team", label: "Team" },
  ];
}

function select_(attrs, options, value, onchange) {
  return h("select", { class: "pick", ...attrs, onchange: (e) => onchange(e.target.value) },
    options.map(([v, label]) => h("option", { value: v, selected: v === value }, label)));
}

function countryOptions() {
  const counts = {};
  for (const e of events()) {
    const k = e.country || "INTL";
    counts[k] = (counts[k] || 0) + 1;
  }
  const home = S.data.settings.home_country;
  const names = Object.fromEntries(S.data.settings.countries);
  const keys = Object.keys(counts).sort((a, b) =>
    (b === home) - (a === home) || (a === "INTL") - (b === "INTL") || counts[b] - counts[a] || a.localeCompare(b));
  return [["", "all countries"], ...keys.map((k) =>
    [k, k === "INTL" ? `international (${counts[k]})` : `${k} · ${names[k] || k} (${counts[k]})`])];
}

function renderFilters() {
  const box = $("#chips");
  box.replaceChildren();
  const chips = chipsFor(S.view);
  if (!chips.some((c) => c.id === S.chip[S.view])) S.chip[S.view] = chips[0].id;
  for (const c of chips) {
    box.append(h("button", {
      class: "chip" + (c.cls ? " " + c.cls : "") + (S.chip[S.view] === c.id ? " active" : ""), title: c.title,
      onclick: () => setChip(c.id),
    }, c.label, c.n ? h("span", { class: "n" }, c.n) : null));
  }

  const pick = $("#pickers");
  pick.replaceChildren();
  const st = S.data.settings;
  if (S.view === "news") {
    const srcs = [...new Set(newsItems().filter((a) => !a.archived).map((a) => a.source))].sort();
    if (S.source && !srcs.includes(S.source)) S.source = "";
    pick.append(select_({ title: "Source" }, [["", "all sources"], ...srcs.map((s) => [s, s])], S.source,
      (v) => { S.source = v; render(); }));
  } else if (S.chip.ctf === "team") {
    pick.append(h("span", { class: "pick-label" }, "rank in"),
      select_({ title: "Country leaderboard" }, st.countries, rankCountry(), setRankCountry));
  } else {
    pick.append(
      select_({ title: "Country — the list always has every country; this narrows it" }, countryOptions(), S.country,
        (v) => { S.country = v; store.set("country", v); render(); }),
      select_({ title: "Online / on-site" }, [["any", "any format"], ["online", "online"], ["onsite", "on-site"],
        ["big", "big events"]], S.mode, (v) => { S.mode = v; store.set("mode", v); render(); }),
      h("span", { class: "pick-icon", html: ICON.clock }),
      select_({ title: "Time zone for start times" }, tzOptions(st, true), st.timezone, setTimezone),
    );
  }
}

function tzOptions(st, short) {
  const local = st.tz_label.replace("-", "−");
  const opts = TZS.map(([v, l]) => [v, v === "" ? (short ? local : `${l} (${local})`) : l]);
  if (st.timezone && !opts.some(([v]) => v === st.timezone)) opts.push([st.timezone, st.timezone]);
  return opts;
}

async function setTimezone(v) {
  await api("/api/settings", { timezone: v });
  toast(v ? "Times now in " + v.replace("-", "−") : "Times now in your local time");
  await load(true);
}

function setChip(id) {
  S.chip[S.view] = id;
  store.set("chip", S.chip);
  render();
  $("#list").scrollTop = 0;
}

function cycleChip(dir) {
  const ids = chipsFor(S.view).map((c) => c.id);
  const i = ids.indexOf(S.chip[S.view]);
  setChip(ids[(i + dir + ids.length) % ids.length]);
}

// ---------------------------------------------------------------- render
function render() {
  if (!S.data) return;
  // keep inline editors (notes, place) from being wiped while typing
  if (document.activeElement && document.activeElement.closest && document.activeElement.closest(".editor")) return;
  document.querySelectorAll(".view").forEach((b) => b.classList.toggle("active", b.dataset.view === S.view));
  renderFilters();
  S.objs.clear();
  const list = $("#list");
  list.replaceChildren();
  if (S.view === "news") renderNews(list);
  else if (S.chip.ctf === "team") renderTeam(list);
  else if (S.chip.ctf === "past") renderPast(list);
  else renderCtf(list);
  S.items = [...list.querySelectorAll("[data-key]")];
  const keep = S.items.find((el) => el.dataset.key === S.sel[S.view]);
  select(keep || S.items[0], false);
  renderHeader();
  renderFooter();
  $("#btn-refresh").classList.toggle("spin", !!S.data.busy);
}

function matches(...fields) {
  if (!S.q) return true;
  const blob = fields.join(" ").toLowerCase();
  return S.q.toLowerCase().split(/\s+/).every((w) => blob.includes(w));
}

function section(title, n, cls) {
  return h("div", { class: "section" + (cls ? " " + cls : "") }, h("span", {}, title),
    n != null ? h("span", { class: "n" }, n) : null);
}

// ---------------- news
function renderNews(list) {
  const chip = S.chip.news;
  const items = newsItems().filter((a) => {
    if (chip === "saved") return a.saved;
    if (a.archived) return false;
    if (chip === "unread" && !a.unread) return false;
    if (chip === "watch" && !a.watch) return false;
    if (chip === "opps" && !a.opportunity) return false;
    if (S.source && a.source !== S.source) return false;
    return matches(a.title, a.summary, a.source, a.domain, a.tags.join(" "));
  });
  if (!items.length) {
    const empty = !newsItems().length;
    list.append(emptyState(empty ? "Fetching the news…" : chip === "opps" ? "No opportunities right now" : "Nothing here",
      empty ? "First run takes a few seconds."
        : chip === "opps" ? "New CTFs, competitions and scholarships show up here as they're announced. You can change the searches in settings."
          : "Try another filter or clear the search."));
    return;
  }
  items.sort((a, b) => (b.published || "").localeCompare(a.published || ""));
  let day = null;
  for (const a of items) {
    const d = dayLabel(a.published);
    if (d !== day) { day = d; list.append(section(d)); }
    list.append(newsCard(a));
  }
}

function initials(src) {
  const w = String(src || "?").replace(/\.(com|net|org|media)$/i, "").split(/[\s.:·-]+/).filter(Boolean);
  return (w.length > 1 ? w.map((x) => x[0]).join("") : String(src || "?").slice(0, 2)).slice(0, 3).toUpperCase();
}

function thumb(src, fallbackText, hueVar, cls) {
  const box = h("div", { class: "thumb" + (cls ? " " + cls : "") });
  const ph = () => h("div", { class: "ph", style: `--hue: var(${hueVar || "--accent"})` }, fallbackText);
  if (!src) { box.append(ph()); return box; }
  const img = h("img", { src, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => box.replaceChildren(ph()));
  box.append(img);
  return box;
}

function newsCard(a) {
  const key = "n:" + a.id;
  S.objs.set(key, { type: "news", obj: a });
  const hue = a.kind === "opportunity" ? "--green" : a.tags.map((t) => TAG_HUE[t]).find(Boolean);
  const src = a.kind === "opportunity" ? (a.thumb || "") : "/img/n/" + a.id;
  const shownTags = a.tags.filter((t) => t !== "OPPORTUNITY" && t !== "CTF").slice(0, 2);
  const card = h("article", {
    class: "card" + (a.unread ? " unread" : "") + (a.watch ? " watch" : "") + (a.opportunity ? " opp" : ""),
    "data-key": key, onclick: () => select(card), ondblclick: () => act("open"),
  },
    thumb(src, a.kind === "opportunity" ? "CTF" : initials(a.source), hue),
    h("div", { class: "body" },
      h("h3", { class: "title" }, a.watch ? h("span", { class: "star" }, "★ ") : null, a.title),
      h("div", { class: "meta" },
        a.opportunity ? [h("span", { class: "opp-tag" }, "opportunity"), dot()] : null,
        h("span", {}, a.domain || a.source), dot(), h("span", {}, ago(a.published)),
        shownTags.map((t) => [dot(), h("span", { class: "t-" + t.toLowerCase() }, t.toLowerCase())]),
        a.saved ? [dot(), h("span", { class: "accent" }, "saved")] : null,
      ),
      a.summary ? h("p", { class: "summary" }, a.summary) : null,
      h("div", { class: "actions" },
        btn(ICON.open, "Open", "o", () => act("open")),
        a.kind !== "opportunity" ? btn(ICON.bookmark, a.saved ? "Unsave" : "Save", "s", () => act("save")) : null,
        a.event_id ? btn(ICON.flag, "Show in CTFs", "", () => showEvent(a.event_id)) : null,
        btn(ICON.copy, "Copy link", "y", () => act("copy")),
      ),
    ),
  );
  return card;
}

function btn(icon, label, key, fn, cls) {
  return h("button", { class: "btn" + (cls ? " " + cls : ""), onclick: (e) => { e.stopPropagation(); fn(); } },
    h("span", { html: icon }), label, key ? h("kbd", {}, key) : null);
}

function showEvent(id) {
  S.view = "ctf";
  S.chip.ctf = "upcoming";
  S.country = ""; S.mode = "any"; S.q = "";
  S.sel.ctf = "c:" + id;
  render();
  const el = document.querySelector(`[data-key="c:${CSS.escape(id)}"]`);
  if (el) select(el);
}

// ---------------- ctf
function rankCountry() {
  const st = S.data.settings;
  return st.rank_country || S.data.team?.team?.country || st.home_country || "RO";
}

function ctfFilter(e) {
  if (S.country && (e.country || "INTL") !== S.country) return false;
  if (S.mode === "online" && e.mode !== "online") return false;
  if (S.mode === "onsite" && e.mode === "online") return false;
  if (S.mode === "big" && !e.big) return false;
  return matches(e.name, e.location, e.organizers, e.format, e.country, e.country_name, e.note, e.kind);
}

function renderCtf(list) {
  const chip = S.chip.ctf;
  const evs = events().filter(ctfFilter);
  const empty = (title, text) => list.append(emptyState(title, text));
  if (!events().length) return empty("Loading CTFs…", "Pulling the calendar from CTFtime.");

  if (chip === "live") {
    const rows = evs.filter((e) => e.live).sort((a, b) => (a.finish || "").localeCompare(b.finish || ""));
    if (!rows.length) return empty("Nothing live right now", "CTFs that have started show up here, in red, with the time left.");
    list.append(section("Live now", rows.length, "live"));
    rows.forEach((e) => list.append(ctfCard(e)));
    return;
  }
  if (chip === "mine") {
    const reg = evs.filter((e) => e.mine === "registered" && !e.past);
    const saved = evs.filter((e) => e.mine === "saved" && !e.past);
    if (!reg.length && !saved.length) {
      return empty("Nothing saved yet", "Press s on a CTF to save it, or i when you've registered. They stay here, and move to Past (with your result) once they end.");
    }
    if (reg.length) { list.append(section("Registered", reg.length)); reg.forEach((e) => list.append(ctfCard(e))); }
    if (saved.length) { list.append(section("Saved", saved.length)); saved.forEach((e) => list.append(ctfCard(e))); }
    return;
  }
  if (chip === "tba") {
    const rows = evs.filter((e) => e.section === "tba");
    if (!rows.length) return empty("Watchlist is empty", "Recurring competitions without announced dates show up here.");
    list.append(section("Dates not announced yet", rows.length));
    rows.forEach((e) => list.append(ctfCard(e)));
    return;
  }
  const groups = [
    ["week", `This week · ${S.data.week[0]} – ${S.data.week[1]}`],
    ["soon", "Next 4 weeks"], ["radar", "Further out · big events"], ["later", "Later"],
  ];
  let any = false;
  for (const [id, title] of groups) {
    const rows = evs.filter((e) => e.section === id && !e.past);
    if (!rows.length) continue;
    any = true;
    list.append(section(title, rows.length));
    rows.forEach((e) => list.append(ctfCard(e)));
  }
  if (!any) empty("No events here", "Try another country or format, or clear the search.");
}

function dateBlock(e) {
  const thisYear = new Date().getFullYear();
  return h("div", { class: "date" },
    e.start
      ? [h("span", { class: "wd" }, e.weekday), h("span", { class: "d" }, e.day),
        h("span", { class: "m" }, e.month + (e.year !== thisYear ? " ’" + String(e.year).slice(2) : ""))]
      : h("span", { class: "tba" }, "TBA"));
}

function statusText(e) {
  if (!e.start) return "TBA";
  if (e.live) return e.countdown.replace("LIVE · ends in ", "") + " left";
  if (e.past) return e.place ? `#${e.place}${e.teams ? " of " + e.teams : ""}` : "ended " + ago(e.finish) + " ago";
  return e.countdown;
}

function ctfCard(e) {
  const key = "c:" + e.id;
  S.objs.set(key, { type: "event", obj: e });
  const tzl = S.data.settings.tz_label.replace("-", "−");
  const timeLine = e.start
    ? (e.source === "ctftime" ? `${e.weekday} ${e.day} ${e.month}, ${e.start_time} → ${e.ends}` : e.range)
    : "dates not announced";

  const meta = h("div", { class: "meta" },
    h("span", { class: "mode" }, e.mode === "onsite" ? "on-site" : e.mode),
    e.weight ? [dot(), h("span", { class: e.big ? "big" : "", title: "CTFtime weight" },
      "▲" + (+e.weight).toFixed(1).replace(/\.0$/, ""))] : null,
    [dot(), h("span", { class: e.home ? "home" : "", title: e.country_long }, e.country_cell + (e.home ? " ★" : ""))],
    e.kind === "conference" ? [dot(), h("span", {}, "conference")] : e.format ? [dot(), h("span", {}, e.format.toLowerCase())] : null,
  );

  const kv = h("dl", { class: "kv" });
  const add = (k, v) => { if (v) kv.append(h("dt", {}, k), h("dd", {}, v)); };
  add("When", e.start ? `${e.range}  (${tzl})` : e.range);
  add("Duration", e.duration ? e.duration + (e.hours && e.source === "ctftime" ? "" : "") : "");
  add("Where", [e.country_long, e.location].filter(Boolean).join(" · "));
  add("Organisers", e.organizers);
  add("Open to", e.restrictions);
  add("Teams", e.participants ? String(e.participants) : "");
  if (e.past && e.place) add("Your result", `#${e.place}${e.teams ? " of " + e.teams : ""}${e.points ? " · " + (+e.points).toFixed(1) + " pts" : ""}${e.result_source === "ctftime" ? " (from CTFtime)" : ""}`);

  const badges = [];
  if (e.live) badges.push(h("span", { class: "badge live" }, "LIVE"));
  if (e.mine === "registered") badges.push(h("span", { class: "badge reg" }, e.past ? "✓ played" : "✓ registered"));
  else if (e.mine === "saved") badges.push(h("span", { class: "badge saved" }, "★ saved"));

  const logo = e.logo ? thumb("/img/c/" + e.id, initials(e.name), e.mode === "online" ? "--cyan" : "--magenta", "logo") : null;

  const card = h("article", {
    class: `card ctf m-${e.mode}` + (e.live ? " live" : "") + (e.home ? " watch" : "") + (e.past ? " past" : ""),
    "data-key": key, onclick: () => select(card), ondblclick: () => act("open"),
  },
    dateBlock(e),
    logo,
    h("div", { class: "body" },
      h("h3", { class: "title" }, badges, e.name),
      h("div", { class: "timeline" }, timeLine),
      meta,
      e.live && e.progress != null ? h("div", { class: "progress" }, h("span", { style: `width:${Math.round(e.progress * 100)}%` })) : null,
      h("div", { class: "details" }, kv,
        (e.note || e.description) ? h("p", { class: "desc" }, (e.note || e.description).slice(0, 420)) : null,
        e.past && e.mine === "registered" ? resultEditor(e) : null),
      h("div", { class: "actions" },
        e.url && !e.past ? btn(ICON.open, "Register", "o", () => act("open")) : null,
        e.past ? null : btn(ICON.bookmark, e.mine === "saved" ? "Saved" : e.mine ? "Remove" : "Save", "s", () => act("save"), e.mine === "saved" ? "on" : ""),
        btn(ICON.check, e.past ? (e.mine === "registered" ? "Didn't play" : "I played this") : (e.mine === "registered" ? "Registered" : "I'm registered"), "i",
          () => act("registered"), e.mine === "registered" && !e.past ? "on" : ""),
        e.ctftime_url ? btn(ICON.flag, "CTFtime", "c", () => act("ctftime")) : null,
        e.start && !e.past ? btn(ICON.cal, "Calendar", "a", () => act("calendar")) : null,
        btn(ICON.copy, "Copy link", "y", () => act("copy")),
      ),
    ),
    h("div", { class: "right" },
      h("div", { class: "dur", title: "How long it runs" }, e.duration || ""),
      h("div", { class: "status" + (e.live ? " live" : "") }, statusText(e)),
    ),
  );
  return card;
}

function resultEditor(e) {
  const save = (patch) => api("/api/mine", { id: e.id, ...patch }).then(() => toast("Saved")).catch(() => toast("Couldn't save"));
  const place = h("input", { class: "small", placeholder: "#", value: e.result_source === "manual" ? e.place || "" : "",
    title: "Your place (leave empty to use CTFtime's result)" });
  const teams = h("input", { class: "small", placeholder: "of", value: e.result_source === "manual" ? e.teams || "" : "" });
  const notes = h("textarea", { rows: 2, placeholder: "Notes — teammates, what you solved, where you stayed…" });
  notes.value = e.notes || "";
  const stop = (ev) => ev.stopPropagation();
  [place, teams, notes].forEach((el) => { el.addEventListener("click", stop); el.addEventListener("dblclick", stop); });
  place.addEventListener("change", () => save({ place: place.value || 0 }));
  teams.addEventListener("change", () => save({ teams: teams.value || 0 }));
  notes.addEventListener("change", () => save({ notes: notes.value }));
  return h("div", { class: "editor" },
    h("label", {}, h("span", {}, "Place"), place, h("span", { class: "muted" }, "of"), teams),
    h("label", { class: "grow" }, h("span", {}, "Notes"), notes));
}

// ---------------- past / history
function renderPast(list) {
  const evs = events().filter((e) => e.past).filter(ctfFilter)
    .sort((a, b) => (b.finish || "").localeCompare(a.finish || ""));
  const mine = evs.filter((e) => e.mine === "registered");
  const rest = evs.filter((e) => e.mine !== "registered");
  const hs = S.data.history || {};

  if (hs.played) {
    list.append(h("div", { class: "history" },
      stat(String(hs.played), hs.played === 1 ? "CTF played" : "CTFs played"),
      stat(String(hs.onsite), "on-site"),
      stat(hs.best ? "#" + hs.best : "—", "best place"),
      stat(hs.hours ? hs.hours + "h" : "—", "of competing"),
      hs.countries.length ? h("div", { class: "places" }, h("span", { class: "muted" }, "Been to"),
        h("span", {}, [...hs.cities, ...hs.countries.filter((c) => !hs.cities.length)].join(" · ") || hs.countries.join(" · "))) : null,
    ));
  } else {
    list.append(h("div", { class: "hint" },
      "Your CTF history builds itself: mark a CTF with i (I'm registered) and once it ends it lands here, " +
      "with your place pulled from CTFtime when your team is set. You can also mark past ones below with “I played this”."));
  }
  if (mine.length) {
    list.append(section("Your CTFs", mine.length));
    mine.forEach((e) => list.append(ctfCard(e)));
  }
  if (rest.length) {
    list.append(section("Ended in the last 60 days", rest.length));
    rest.forEach((e) => list.append(ctfCard(e)));
  }
  if (!evs.length) list.append(emptyState("No past events yet", "Ended CTFs from the last 60 days appear after the next refresh."));
}

// ---------------- team
async function loadTop(cc) {
  if (S.top && S.top.country === cc && !S.top.loading) return;
  S.top = { country: cc, rows: [], loading: true };
  try {
    const r = await api("/api/top?cc=" + cc);
    S.top = { country: cc, rows: r.rows || [], name: r.name, error: r.error };
  } catch { S.top = { country: cc, rows: [], error: "offline" }; }
  if (S.view === "ctf" && S.chip.ctf === "team") render();
}

async function setRankCountry(cc) {
  S.top = null;
  api("/api/settings", { rank_country: cc }).catch(() => {});
  S.data.settings.rank_country = cc;
  render();
}

function renderTeam(list) {
  const t = S.data.team || {};
  const st = S.data.settings;
  const cc = rankCountry();
  const cname = (st.countries.find(([c]) => c === cc) || [cc, cc])[1];
  if (!S.top || S.top.country !== cc) loadTop(cc);
  const rows = S.top && S.top.country === cc ? S.top.rows : [];
  const me = st.team_id ? rows.find((r) => String(r.id) === String(st.team_id)) : null;
  const tm = t.team;

  if (!st.team_id) {
    list.append(h("div", { class: "hint" },
      "Add your CTFtime team in settings to see where you stand. CTFtime has no API keys — your public team ID is enough. ",
      h("button", { class: "link", onclick: openSettings }, "Open settings")));
  } else if (tm) {
    const place = me ? me.country_place || rows.indexOf(me) + 1 : (tm.country === cc ? tm.country_place : null);
    const key = "t:me";
    S.objs.set(key, { type: "link", obj: { url: tm.url } });
    const av = thumb("/img/t/" + tm.id, initials(tm.name));
    av.className = "avatar";
    list.append(h("div", { class: "team", "data-key": key, onclick: () => act("open") },
      av,
      h("div", { class: "team-body" },
        h("div", { class: "team-name" }, tm.name),
        h("div", { class: "stats" },
          stat(place ? "#" + place : "—", "in " + cname),
          stat(tm.place ? "#" + tm.place : "—", "world " + tm.year),
          stat(tm.points != null ? (+tm.points).toFixed(1) : "—", "points"),
        ),
      ),
    ));
    if (!place && cc !== tm.country) {
      list.append(h("div", { class: "hint" }, `${tm.name} is registered in ${tm.country || "another country"}, so it has no rank in ${cname}.`));
    }
  }

  if (t.results && t.results.length) {
    list.append(section("Recent results", t.results.length));
    for (const r of t.results) {
      const key = "r:" + r.event_id;
      S.objs.set(key, { type: "link", obj: r });
      const el = h("div", { class: "rowi", "data-key": key, onclick: () => select(el), ondblclick: () => act("open") },
        h("span", { class: "p" }, `#${r.place}`), h("span", { class: "nm" }, r.title, h("span", { class: "muted" }, ` / ${r.teams}`)),
        h("span", { class: "pts" }, (+r.points).toFixed(1)));
      list.append(el);
    }
  }

  list.append(section("Top teams · " + cname, rows.length || null));
  if (S.top && S.top.loading) list.append(h("div", { class: "hint" }, "Loading…"));
  else if (!rows.length) list.append(h("div", { class: "hint" }, S.top?.error ? "Couldn't reach CTFtime." : "No ranked teams."));
  rows.forEach((r, i) => {
    const key = "x:" + r.id;
    S.objs.set(key, { type: "link", obj: { url: "https://ctftime.org/team/" + r.id } });
    const el = h("div", { class: "rowi" + (r === me ? " me" : ""), "data-key": key,
      onclick: () => select(el), ondblclick: () => act("open") },
      h("span", { class: "p" }, "#" + (r.country_place || i + 1)),
      h("span", { class: "nm" }, r.name, r.place ? h("span", { class: "muted" }, `  #${r.place} world`) : null),
      h("span", { class: "pts" }, r.points != null ? (+r.points).toFixed(1) : ""));
    list.append(el);
  });
}

function stat(v, label) { return h("div", { class: "stat" }, h("b", {}, v), h("span", {}, label)); }

function emptyState(title, text) {
  return h("div", { class: "empty" }, h("b", {}, title), text);
}

// ---------------------------------------------------------------- header / footer
function renderHeader() {
  const c = $("#headline-count");
  if (S.view === "news") {
    const n = newsItems().filter((a) => a.unread && !a.archived).length;
    c.textContent = n ? `${n} unread` : "";
  } else {
    const n = events().filter((e) => e.section === "week" && !e.past).length;
    const live = events().filter((e) => e.live).length;
    c.replaceChildren(live ? h("span", { class: "live-count" }, `● ${live} live`) : n ? `${n} this week` : "");
  }
}

function renderFooter() {
  if (!S.data) return;
  const left = $("#foot-left"), right = $("#foot-right");
  left.textContent = S.view === "news"
    ? `${newsItems().filter((a) => !a.archived).length} stories · ${mb(S.data.artwork_bytes || 0)} of artwork`
    : `${events().length} events · ctftime.org`;
  right.replaceChildren();
  const errs = Object.entries(S.data.errors || {});
  if (errs.length) {
    right.append(h("span", { class: "err", title: errs.map(([k, v]) => `${k}: ${v}`).join("\n") },
      `${errs.length} source${errs.length > 1 ? "s" : ""} failed`), dot());
  }
  right.append(S.data.busy ? "refreshing…" : S.data.updated ? `updated ${ago(S.data.updated)} ago`.replace("now ago", "just now") : "not updated yet");
}

// ---------------------------------------------------------------- selection + actions
function select(el, scroll = true) {
  if (!el) return;
  S.items.forEach((x) => x.classList.toggle("sel", x === el));
  S.sel[S.view] = el.dataset.key;
  if (scroll) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function move(d) {
  if (!S.items.length) return;
  const i = S.items.findIndex((x) => x.dataset.key === S.sel[S.view]);
  select(S.items[Math.max(0, Math.min(S.items.length - 1, (i < 0 ? 0 : i + d)))]);
}

const current = () => S.objs.get(S.sel[S.view]);

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (t.hidden = true), 1600);
}

async function openUrl(url) {
  if (!url) return;
  try { await api("/api/open", { url }); toast("Opened in browser"); }
  catch { window.open(url, "_blank", "noopener"); }
}

async function act(what) {
  const cur = current();
  if (!cur) return;
  const { type, obj } = cur;
  const link = type === "news" ? obj.link : type === "event" ? (obj.url || obj.ctftime_url) : obj.url;
  if (what === "open") {
    await openUrl(link);
    if (type === "news" && obj.unread) {
      obj.unread = false;
      api("/api/read", { ids: [obj.id] }).catch(() => {});
      document.querySelector(`[data-key="n:${obj.id}"]`)?.classList.remove("unread");
      renderHeader();
    }
  } else if (what === "ctftime" && type === "event") {
    obj.ctftime_url ? openUrl(obj.ctftime_url) : toast("No CTFtime page for this one");
  } else if (what === "copy") {
    try { await navigator.clipboard.writeText(link); toast("Link copied"); }
    catch { toast(link); }
  } else if (what === "save" && type === "news") {
    if (obj.kind === "opportunity") return;
    obj.saved = !obj.saved;
    await api("/api/save", { id: obj.id, saved: obj.saved });
    toast(obj.saved ? "Saved" : "Removed from saved");
  } else if (what === "save" && type === "event") {
    if (obj.past) return;
    const status = obj.mine ? "none" : "saved";
    await api("/api/mine", { id: obj.id, status });
    toast(status === "none" ? "Removed from Mine" : "Saved — find it under Mine");
  } else if (what === "registered" && type === "event") {
    const status = obj.mine === "registered" ? (obj.past ? "none" : "saved") : "registered";
    await api("/api/mine", { id: obj.id, status });
    toast(status === "registered" ? (obj.past ? "Added to your history" : "Marked as registered — good luck!")
      : obj.past ? "Removed from your history" : "No longer marked as registered");
  } else if (what === "calendar" && type === "event" && obj.start) {
    location.href = "/api/ics/" + obj.id;
  }
}

async function refresh() {
  await api("/api/refresh", {});
  $("#btn-refresh").classList.add("spin");
}

async function markAllRead() {
  await api("/api/read", { all: true });
  toast("All marked read");
}

function setView(v) {
  S.view = v;
  store.set("view", v);
  render();
}

// ---------------------------------------------------------------- search
function toggleSearch(open) {
  const wrap = $("#search-wrap"), input = $("#search");
  const want = open ?? !wrap.classList.contains("open");
  wrap.classList.toggle("open", want);
  if (want) { input.focus(); input.select(); }
  else { input.value = ""; S.q = ""; render(); $("#list").focus(); }
}

// ---------------------------------------------------------------- settings
function openSettings() {
  const st = S.data.settings, f = $("#settings-form");
  f.team_id.value = st.team_id || "";
  $("#set-country").replaceChildren(...st.countries.map(([c, n]) =>
    h("option", { value: c, selected: c === st.home_country }, n)));
  $("#set-tz").replaceChildren(...tzOptions(st).map(([v, l]) =>
    h("option", { value: v, selected: v === st.timezone }, l)));
  f.big_weight.value = st.big_weight;
  f.watch_words.value = (st.watch_words || []).join(", ");
  f.opportunity_queries.value = (st.opportunity_queries || []).join("\n");
  $("#feed-list").replaceChildren(...st.feeds.map((fd) => h("label", { class: "feed" },
    h("input", { type: "checkbox", "data-name": fd.name, "data-url": fd.url, "data-builtin": fd.builtin ? "1" : "", checked: fd.enabled }),
    fd.name, h("span", { class: "u" }, fd.url.replace(/^https?:\/\//, "")),
    fd.builtin ? null : h("button", { type: "button", class: "icon tiny", title: "Remove this feed", html: ICON.close,
      onclick: (ev) => { ev.preventDefault(); ev.currentTarget.closest(".feed").remove(); } }))));
  $("#theme-name").textContent = "theme: " + (S.data.theme || "default");
  $("#drawer").hidden = false;
  f.team_id.focus();
}
function closeSettings() { $("#drawer").hidden = true; $("#list").focus(); }

async function saveSettings(ev) {
  ev.preventDefault();
  const f = ev.target;
  const boxes = [...document.querySelectorAll("#feed-list input")];
  const extra = {};
  boxes.filter((b) => !b.dataset.builtin).forEach((b) => (extra[b.dataset.name] = b.dataset.url));
  const nn = $("#new-feed-name").value.trim(), nu = $("#new-feed-url").value.trim();
  if (nn && nu) extra[nn] = nu;
  await api("/api/settings", {
    team_id: f.team_id.value.trim(),
    home_country: f.home_country.value,
    timezone: f.timezone.value,
    big_weight: f.big_weight.value,
    watch_words: f.watch_words.value.split(",").map((s) => s.trim()).filter(Boolean),
    disabled_feeds: boxes.filter((b) => !b.checked).map((b) => b.dataset.name),
    extra_feeds: extra,
    opportunity_queries: f.opportunity_queries.value.split("\n").map((q) => q.trim()).filter(Boolean),
  });
  $("#new-feed-name").value = $("#new-feed-url").value = "";
  closeSettings();
  S.top = null;
  toast("Saved");
  await load(true);
}

// ---------------------------------------------------------------- keys
document.addEventListener("keydown", (e) => {
  const inInput = e.target.matches("input, textarea, select");
  if (e.key === "Escape") {
    if (!$("#drawer").hidden) return closeSettings();
    if ($("#search-wrap").classList.contains("open")) return toggleSearch(false);
    if (inInput) return e.target.blur();
    return;
  }
  if (!$("#drawer").hidden && !inInput) return;
  if (inInput) {
    if (e.target.id === "search") {
      if (e.key === "Enter") $("#list").focus();
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); move(e.key === "ArrowDown" ? 1 : -1); }
    }
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const map = {
    j: () => move(1), ArrowDown: () => move(1), k: () => move(-1), ArrowUp: () => move(-1),
    g: () => select(S.items[0]), G: () => select(S.items[S.items.length - 1]),
    PageDown: () => move(6), PageUp: () => move(-6),
    Enter: () => act("open"), o: () => act("open"), s: () => act("save"), y: () => act("copy"),
    c: () => act("ctftime"), a: () => act("calendar"), i: () => act("registered"),
    "1": () => setView("news"), "2": () => setView("ctf"),
    Tab: () => setView(S.view === "news" ? "ctf" : "news"),
    l: () => cycleChip(1), h: () => cycleChip(-1), ArrowRight: () => cycleChip(1), ArrowLeft: () => cycleChip(-1),
    "/": () => toggleSearch(true), r: refresh, m: markAllRead, ",": openSettings,
    t: () => { S.view = "ctf"; setChip("team"); },
    L: () => { S.view = "ctf"; setChip("live"); }, p: () => { S.view = "ctf"; setChip("past"); },
  };
  if (map[e.key]) { e.preventDefault(); map[e.key](); }
});

// ---------------------------------------------------------------- boot
function boot() {
  $("#btn-search").innerHTML = ICON.search;
  $("#btn-refresh").innerHTML = ICON.refresh;
  $("#btn-settings").innerHTML = ICON.settings;
  $("#btn-close").innerHTML = ICON.close;
  $("#btn-search").onclick = () => toggleSearch();
  $("#btn-refresh").onclick = refresh;
  $("#btn-settings").onclick = openSettings;
  $("#btn-close").onclick = closeSettings;
  $("#settings-form").addEventListener("submit", saveSettings);
  document.querySelectorAll(".view").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
  $("#search").addEventListener("input", (e) => { S.q = e.target.value.trim(); render(); });

  const hash = location.hash.slice(1);
  if (hash === "news" || hash === "ctf") S.view = hash;
  if (hash === "team") { S.view = "ctf"; S.chip.ctf = "team"; }

  setInterval(renderFooter, 30000);
  setInterval(() => load(), 60000); // safety net if the event stream drops
  load(true);
  listen();
  watchTheme();
}
boot();
