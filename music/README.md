# Music Board

Same design as the Software Board. GitHub Actions fetch the charts daily and commit JSON; `index.html` (GitHub Pages) reads it.

| Tab | Source | Ranked by | Bottom of each tile |
|---|---|---|---|
| All | the four below | equal-weight score | score and how many charts the song is on, plus a chip per chart with ranks, streams and views |
| Spotify | kworb.net global daily chart | daily streams | streams |
| Billboard | `mhollingshead/billboard-hot-100` JSON on raw.githubusercontent.com | Hot 100 position | weeks on chart, peak |
| iTunes | Apple Music top songs RSS | Apple chart position | Apple rank |
| YouTube | YouTube Data API, US music category (`videoCategoryId=10`) | most popular | views |

**All ranking:** each chart gives a song `101 - rank` points (0 if absent) and the points are averaged, so every chart has equal weight. Songs are matched across charts by normalised title plus artist.

**Links:** every song shows Spotify, Apple, Video and Billboard buttons. A direct link is used when found; otherwise a greyed search link (Billboard only shows when the song charts there, and links to that week's Hot 100 page).

**Time frame:** Current is the top 100 right now (any release date). 1, 2, 3, 6 and 12 Months show only the songs from that top 100 released in the last N months, keeping their top 100 rank. Songs with no known release date appear only in Current.

## Setup
1. New GitHub repo (e.g. `music`) with these files. Settings > Actions > Workflow permissions: Read and write. Settings > Pages: main branch, root.
2. Create a free YouTube Data API v3 key (Google Cloud Console) and add it as repo secret `YOUTUBE_API_KEY`. The other three sources need no key.
3. Actions tab: run *Update music rankings*. The first run is slow (iTunes search is rate limited, about 250 songs per run, cached in `state/`); later runs fill the rest.

Local: `pip install -r requirements.txt`, `YOUTUBE_API_KEY=... python music.py`, `python -m http.server`.

## Notes
* A source that fails keeps its previous JSON, and `all` is rebuilt from whatever is available.
* kworb is HTML, not an API, so the parser could break if its table layout changes. The Billboard JSON comes from a community repo; check that it is still updating.
* Dates are Apple release dates, falling back to the YouTube upload date.
* `ITUNES_SEARCH_BUDGET` (default 250) sets iTunes lookups per run.
