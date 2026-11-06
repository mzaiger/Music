#!/usr/bin/env python3
"""Music Board data builder: Spotify (kworb), Billboard (raw.githubusercontent), iTunes, YouTube -> data/*.json.
Usage: python music.py   (YOUTUBE_API_KEY env var needed for the YouTube source)"""
import json, os, re, time, unicodedata
from datetime import datetime, timezone
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

TOP_N = 100
UA = {"User-Agent": "Mozilla/5.0 (compatible; music-board/1.0)"}
YT_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SEARCH_BUDGET = int(os.environ.get("ITUNES_SEARCH_BUDGET", "250"))   # iTunes lookups per run (cached afterwards)
NOW = datetime.now(timezone.utc)
SRC = ["spotify", "billboard", "itunes", "youtube"]


def get(url, params=None, retries=3, as_json=True):
    last = None
    for a in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=30)
            if r.status_code in (403, 429) or r.status_code >= 500:
                last = f"HTTP {r.status_code}"; time.sleep(5 * (a + 1)); continue
            r.raise_for_status()
            return r.json() if as_json else r.text
        except (requests.RequestException, ValueError) as e:
            last = str(e); time.sleep(3 * (a + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def dump(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- matching songs across sources
def nt(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"\s-\s.*$", "", s)
    s = re.sub(r"\b(feat|ft|featuring)\b.*$", " ", s).replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s)).strip()


def artists(s):
    parts = re.split(r",|&|\band\b|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\+", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())
    return {re.sub(r"[^a-z0-9 ]", "", p).strip() for p in parts if re.sub(r"[^a-z0-9 ]", "", p).strip()}


def same(t1, a1, t2, a2):
    return bool(t1) and t1 == t2 and bool(a1 & a2)


def split_video(title, channel):
    t = re.sub(r"\(.*?(official|video|lyric|audio|visuali[sz]er|live).*?\)|\[.*?(official|video|lyric|audio|visuali[sz]er|live).*?\]", "", title, flags=re.I)
    t = re.sub(r"\s*\|.*$", "", t).strip()
    if " - " in t:
        a, s = t.split(" - ", 1)
        return s.strip(), a.strip()
    return t, re.sub(r"\s*(- Topic|VEVO)$", "", channel, flags=re.I).strip()


# ---------------------------------------------------------------- sources: each returns [{rank,title,artist,url,metric,...}]
def fetch_spotify():
    html = get("https://kworb.net/spotify/country/global_daily.html", as_json=False)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        link = tr.find("a", href=re.compile(r"track/([A-Za-z0-9]+)\.html"))
        if not link or len(tds) < 8:
            continue
        tid = re.search(r"track/([A-Za-z0-9]+)\.html", link["href"]).group(1)
        names = [a.get_text(strip=True) for a in tr.find_all("a", href=re.compile(r"artist/"))]
        i = next(n for n, td in enumerate(tds) if td.find("a", href=re.compile(r"track/")))
        num = lambda k: int(re.sub(r"\D", "", tds[k].get_text()) or 0) if k < len(tds) else 0
        out.append({"rank": int(re.sub(r"\D", "", tds[0].get_text()) or len(out) + 1), "title": link.get_text(strip=True),
                    "artist": ", ".join(names), "id": tid, "url": f"https://open.spotify.com/track/{tid}",
                    "metric": num(i + 4), "total": num(i + 8)})
    if not out:
        raise RuntimeError("no rows parsed from kworb")
    return out[:TOP_N]


def fetch_billboard():
    d = get("https://raw.githubusercontent.com/mhollingshead/billboard-hot-100/main/recent.json")
    url = f"https://www.billboard.com/charts/hot-100/{d['date']}/"
    return [{"rank": r["this_week"], "title": r["song"], "artist": r["artist"], "id": re.sub(r"[^a-z0-9]+", "-", f"{r['song']} {r['artist']}".lower()).strip("-"), "url": url, "prev": r.get("last_week"),
             "metric": r.get("weeks_on_chart") or 0, "peak": r.get("peak_position") or r["this_week"], "chart_date": d["date"]}
            for r in d["data"][:TOP_N]]


def fetch_itunes():
    try:
        rs = get(f"https://rss.applemarketingtools.com/api/v2/us/music/most-played/{TOP_N}/songs.json")["feed"]["results"]
        return [{"rank": i, "title": r["name"], "artist": r["artistName"], "id": str(r["id"]), "url": r["url"], "metric": i,
                 "image": re.sub(r"/\d+x\d+bb", "/600x600bb", r.get("artworkUrl100", "")), "date": (r.get("releaseDate") or "")[:10]}
                for i, r in enumerate(rs, 1)]
    except Exception as ex:                               # legacy feed fallback
        print(f"  apple marketing feed failed ({ex}); trying legacy feed")
        es = get(f"https://itunes.apple.com/us/rss/topsongs/limit={TOP_N}/json")["feed"]["entry"]
        return [{"rank": i, "title": e["im:name"]["label"], "artist": e["im:artist"]["label"], "id": e["id"]["attributes"]["im:id"],
                 "url": e["id"]["label"], "metric": i, "image": re.sub(r"/\d+x\d+bb", "/600x600bb", e["im:image"][-1]["label"]),
                 "date": ((e.get("im:releaseDate") or {}).get("label") or "")[:10]} for i, e in enumerate(es, 1)]


def fetch_youtube():
    if not YT_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is not set")
    out, token = [], None
    while len(out) < TOP_N:
        p = {"part": "snippet,statistics", "chart": "mostPopular", "videoCategoryId": "10", "regionCode": "US", "maxResults": 50, "key": YT_KEY}
        if token:
            p["pageToken"] = token
        d = get("https://www.googleapis.com/youtube/v3/videos", p)
        for v in d.get("items", []):
            title, artist = split_video(v["snippet"]["title"], v["snippet"].get("channelTitle", ""))
            th = v["snippet"]["thumbnails"]
            out.append({"rank": len(out) + 1, "title": title, "artist": artist, "id": v["id"], "url": f"https://www.youtube.com/watch?v={v['id']}",
                        "metric": int(v.get("statistics", {}).get("viewCount", 0)), "thumb": (th.get("high") or th.get("medium") or {}).get("url", ""),
                        "date": v["snippet"]["publishedAt"][:10]})
        token = d.get("nextPageToken")
        if not token:
            break
    return out[:TOP_N]


FETCH = {"spotify": fetch_spotify, "billboard": fetch_billboard, "itunes": fetch_itunes, "youtube": fetch_youtube}
LABEL = {"spotify": "streams", "billboard": "weeks on chart", "itunes": "apple ranking", "youtube": "views"}


# ---------------------------------------------------------------- merge, enrich, write
def build():
    os.makedirs("data", exist_ok=True); os.makedirs("state", exist_ok=True)
    raw, failed = {}, []
    for s in SRC:
        print(f"[{s}]")
        try:
            raw[s] = FETCH[s]()
            print(f"  {len(raw[s])} rows")
        except Exception as ex:
            print(f"  {s} FAILED: {ex}")
            failed.append(s)
            old = load(f"data/{s}.json", {}).get("items", [])     # keep last good data for this source
            if old:
                raw[s] = [{**o, "rank": o["rank"], "url": o["links"].get({"spotify": "spotify", "billboard": "billboard", "itunes": "itunes", "youtube": "video"}[s], ""),
                           "image": o.get("art", ""), "thumb": o.get("thumb", ""), "metric": o["metric"], "id": o["id"].split(":", 1)[-1],
                           "peak": o.get("peak", o["rank"]), "prev": o.get("prev"), "total": o.get("total", 0), "date": o.get("date", "")} for o in old]
    if not raw:
        raise SystemExit("every source failed")
    if len(failed) == len(SRC):
        raise SystemExit(1)

    groups = []                                                     # one group per song, members keyed by source
    for s, rows in raw.items():
        for r in rows:
            t, a = nt(r["title"]), artists(r["artist"])
            g = next((g for g in groups if same(t, a, g["t"], g["a"])), None)
            if not g:
                g = {"t": t, "a": set(), "title": r["title"], "artist": r["artist"], "m": {}}
                groups.append(g)
            g["a"] |= a
            if s not in g["m"] or r["rank"] < g["m"][s]["rank"]:
                g["m"][s] = r

    n = len(raw)
    for g in groups:                                                # equal weights: each chart gives 101 - rank points, averaged over charts
        g["score"] = round(sum(TOP_N + 1 - g["m"][s]["rank"] for s in g["m"]) / n, 1)
        g["best"] = min(m["rank"] for m in g["m"].values())
    groups.sort(key=lambda g: (-g["score"], -len(g["m"]), g["best"], g["title"]))

    # iTunes search fills Apple link, cover art and release date for songs not on the Apple chart (cached, budgeted)
    sc_path = "state/itunes_search.json"; sc = load(sc_path, {}); budget = SEARCH_BUDGET
    for g in groups:
        key = f"{g['t']}|{sorted(g['a'])[:1]}"
        if "itunes" in g["m"]:
            continue
        if key not in sc and budget > 0:
            budget -= 1
            hit = {}
            try:
                d = get("https://itunes.apple.com/search", {"term": f"{g['title']} {g['artist']}", "entity": "song", "media": "music", "limit": 5, "country": "us"}, retries=2)
                for r in d.get("results", []):
                    if same(g["t"], g["a"], nt(r.get("trackName")), artists(r.get("artistName"))):
                        hit = {"url": r.get("trackViewUrl", ""), "image": re.sub(r"/\d+x\d+bb", "/600x600bb", r.get("artworkUrl100", "")), "date": (r.get("releaseDate") or "")[:10]}
                        break
                sc[key] = hit
            except Exception as ex:
                print(f"  itunes search failed: {ex}")
            time.sleep(3.2)                                         # Apple allows roughly 20 searches a minute
        g["sx"] = sc.get(key) or {}
    dump(sc_path, sc)

    oc_path = "state/spotify_art.json"; oc = load(oc_path, {}); ob = 150
    for g in groups:                                                # Spotify cover art as a fallback image
        sp = g["m"].get("spotify")
        art = (g["m"].get("itunes") or {}).get("image") or g.get("sx", {}).get("image") or ""
        if not art and sp:
            if sp["id"] not in oc and ob > 0:
                ob -= 1
                try:
                    oc[sp["id"]] = get("https://open.spotify.com/oembed", {"url": sp["url"]}, retries=1).get("thumbnail_url", "")
                except Exception:
                    oc[sp["id"]] = ""
                time.sleep(0.4)
            art = oc.get(sp["id"], "")
        g["art"] = art
    dump(oc_path, oc)

    def compact(x):
        return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.0f}K" if x >= 1e3 else str(x)

    def item(g, own):
        m = g["m"]; yt = m.get("youtube", {}); bb = m.get("billboard", {})
        ranks = {s: m[s]["rank"] for s in m}
        metrics = {s: m[s]["metric"] for s in m if s in ("spotify", "youtube")}
        parts = []
        if bb: parts.append(f"Billboard Hot 100 #{bb['rank']} (peak #{bb['peak']}, {bb['metric']} week{'s' if bb['metric'] != 1 else ''}).")
        if "spotify" in m: parts.append(f"#{ranks['spotify']} on Spotify's global daily chart with {m['spotify']['metric']:,} streams.")
        if "itunes" in m: parts.append(f"#{ranks['itunes']} on Apple Music's top songs.")
        if yt: parts.append(f"#{ranks['youtube']} on YouTube's music videos with {yt['metric']:,} views.")
        links = {"spotify": m.get("spotify", {}).get("url", ""), "itunes": (m.get("itunes") or {}).get("url") or g.get("sx", {}).get("url", ""),
                 "video": yt.get("url", ""), "billboard": bb.get("url", "")}
        date = (m.get("itunes") or {}).get("date") or g.get("sx", {}).get("date") or yt.get("date", "")
        it = {"id": own["id"] if own else g["t"].replace(" ", "-") + "-" + "-".join(sorted(g["a"])[:1]).replace(" ", "-"),
              "title": g["title"], "artist": g["artist"], "desc": " ".join(parts) or "No description provided.",
              "image": g["art"] or yt.get("thumb", ""), "art": g["art"], "thumb": yt.get("thumb", ""), "date": date,
              "links": {k: v for k, v in links.items() if v}, "ranks": ranks, "metrics": metrics}
        return it

    updated = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    hp = "state/history.json"; hist = load(hp, {}); today = NOW.strftime("%Y-%m-%d")

    def baseline(s):                                                # snapshot closest to 7 days ago (at least 6 days old)
        best = None
        for d, snap in hist.items():
            age = (NOW.date() - datetime.strptime(d, "%Y-%m-%d").date()).days
            if age >= 6 and s in snap and (best is None or abs(age - 7) < abs(best[0] - 7)):
                best = (age, d)
        return (best[1], hist[best[1]][s]) if best else (None, {})
    snap = {}
    for s in raw:
        rows = sorted((g for g in groups if s in g["m"]), key=lambda g: g["m"][s]["rank"])
        bd, bm = baseline(s); items = []
        for g in rows:
            own = g["m"][s]; it = item(g, own)
            it.update({"id": f"{s}:{own['id']}", "rank": own["rank"], "metric": own["metric"]})
            if s == "youtube": it["image"] = own.get("thumb") or it["image"]
            if s == "billboard": it["peak"] = own["peak"]
            if s == "spotify": it["total"] = own.get("total", 0)
            prev = own.get("prev") if s == "billboard" else bm.get(it["id"])    # Billboard supplies its own last-week rank
            if prev: it["prev"] = prev
            items.append(it)
        items = items[:TOP_N]
        if s not in failed: snap[s] = {i["id"]: i["rank"] for i in items}
        dump(f"data/{s}.json", {"source": s, "metric": LABEL[s], "updated": updated, "trend_base": "last week" if s == "billboard" else bd, "items": items})
        print(f"  wrote data/{s}.json: {len(items)} items")
    allr = []
    for i, g in enumerate(groups[:TOP_N], 1):
        it = item(g, None); it.update({"rank": i, "metric": g["score"], "n": len(g["m"]), "of": n}); allr.append(it)
    bd, bm = baseline("all")
    for it in allr:
        if bm.get(it["id"]): it["prev"] = bm[it["id"]]
    snap["all"] = {i["id"]: i["rank"] for i in allr}
    dump("data/all.json", {"source": "all", "metric": "score", "updated": updated, "sources": list(raw), "trend_base": bd, "items": allr})
    hist.setdefault(today, {}).update(snap)                         # keep three weeks of daily snapshots
    hist = {d: v for d, v in hist.items() if (NOW.date() - datetime.strptime(d, "%Y-%m-%d").date()).days <= 21}
    dump(hp, hist)
    print(f"  wrote data/all.json: {len(allr)} items (equal weight across {list(raw)})")


if __name__ == "__main__":
    build()
