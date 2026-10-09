"""Shared Wikipedia / Wikidata client and Cricsheet identity resolution.

All enrichment modules go through this file so that HTTP etiquette, caching,
retry behaviour and the person-identity join live in one place.

Identity chain: Wikipedia title -> Wikidata item (pageprops) -> ESPNcricinfo id
(Wikidata P2697, or a {{Cricinfo|id=}} template in the article) -> Cricsheet
people register (key_cricinfo / _2 / _3) -> Cricsheet eight-hex identifier.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

API = "https://en.wikipedia.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
USER_AGENT = ("best-eleven-lab/0.3 (https://github.com/Bongo-Seakhoa/best-eleven-lab; "
              "open cricket analytics; contact via GitHub issues)")
CRICINFO_RE = re.compile(r"\{\{\s*[Cc]ricinfo\s*\|[^}]*?\bid\s*=\s*(\d+)", re.S)


class Wiki:
    """Polite, cached MediaWiki API client. Cache keys are request hashes."""

    def __init__(self, cache_dir: str | Path = "data/cache/wiki", *, min_interval: float = 0.25,
                 refresh: bool = False):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.min_interval = min_interval
        self.refresh = refresh
        self._last = 0.0

    # ------------------------------------------------------------------ http
    def _get(self, url: str, params: dict, *, accept: str | None = None, timeout: int = 90):
        key = hashlib.sha256((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:32]
        path = self.cache / f"{key}.json"
        if path.exists() and not self.refresh:
            return json.loads(path.read_text(encoding="utf-8"))
        headers = {"Accept": accept} if accept else {}
        for attempt in range(6):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=timeout)
            except requests.RequestException:
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            r.raise_for_status()
            data = r.json() if "json" in r.headers.get("Content-Type", "") else {"text": r.text}
            if isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag":
                time.sleep(5)
                continue
            path.write_text(json.dumps(data), encoding="utf-8")
            return data
        raise RuntimeError(f"request failed after retries: {url} {params}")

    def api(self, **params) -> dict:
        params = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        return self._get(API, params)

    # ----------------------------------------------------------------- pages
    def parse(self, title: str, *, section: int | None = None) -> dict:
        """Rendered HTML of a page (or one section). Returns title, revid, html."""
        params = {"action": "parse", "page": title, "prop": "text|revid", "redirects": "1"}
        if section is not None:
            params["section"] = str(section)
        d = self.api(**params)
        if "error" in d:
            raise KeyError(f"{title}: {d['error'].get('info')}")
        p = d["parse"]
        return {"title": p["title"], "revid": p.get("revid"), "html": p["text"]}

    def sections(self, title: str) -> list[dict]:
        d = self.api(action="parse", page=title, prop="sections", redirects="1")
        if "error" in d:
            raise KeyError(f"{title}: {d['error'].get('info')}")
        return d["parse"]["sections"]

    def wikitext(self, titles: Iterable[str]) -> dict[str, dict]:
        """Batch-fetch wikitext. Keys are the requested titles; values carry the
        resolved title, revid, Wikidata item and text (None when missing)."""
        titles = list(dict.fromkeys(t for t in titles if t))
        out: dict[str, dict] = {}
        for i in range(0, len(titles), 50):
            batch = titles[i:i + 50]
            d = self.api(action="query", prop="revisions|pageprops", rvprop="content|ids",
                         rvslots="main", ppprop="wikibase_item", redirects="1",
                         titles="|".join(batch))
            q = d.get("query", {})
            alias = {}
            for k in ("normalized", "redirects"):
                for m in q.get(k, []):
                    alias[m["from"]] = m["to"]
            pages = {p["title"]: p for p in q.get("pages", [])}
            for t in batch:
                final = t
                for _ in range(4):
                    if final in alias:
                        final = alias[final]
                p = pages.get(final)
                if not p or p.get("missing") or "revisions" not in p:
                    out[t] = {"title": final, "revid": None, "qid": None, "text": None}
                    continue
                rev = p["revisions"][0]
                out[t] = {"title": final, "revid": rev.get("revid"),
                          "qid": p.get("pageprops", {}).get("wikibase_item"),
                          "text": rev["slots"]["main"]["content"]}
        return out

    # -------------------------------------------------------------- wikidata
    def wikidata_cricinfo(self) -> pd.DataFrame:
        """Every Wikidata item with an ESPNcricinfo player id, plus its enwiki title."""
        q = ("SELECT ?item ?c ?article WHERE { ?item wdt:P2697 ?c . OPTIONAL { ?article schema:about ?item ; "
             "schema:isPartOf <https://en.wikipedia.org/> . } }")
        d = self._get(SPARQL, {"query": q}, accept="text/csv", timeout=180)
        df = pd.read_csv(io.StringIO(d["text"]), dtype=str)
        df["qid"] = df["item"].str.rsplit("/", n=1).str[-1]
        df["cricinfo"] = pd.to_numeric(df["c"], errors="coerce").astype("Int64")
        df["title"] = df["article"].map(title_from_url)
        return df[["qid", "cricinfo", "title"]].dropna(subset=["cricinfo"])


def title_from_url(url) -> str | None:
    if not isinstance(url, str) or "/wiki/" not in url:
        return None
    from urllib.parse import unquote
    return unquote(url.split("/wiki/", 1)[1]).replace("_", " ")


class Resolver:
    """Map Wikipedia titles / Wikidata items / cricinfo ids to Cricsheet ids."""

    def __init__(self, people_csv: str | Path, wiki: Wiki):
        self.wiki = wiki
        people = pd.read_csv(people_csv, dtype=str)
        self.by_cricinfo: dict[int, str] = {}
        for col in ("key_cricinfo", "key_cricinfo_2", "key_cricinfo_3"):
            if col in people:
                for ident, ci in zip(people["identifier"], people[col]):
                    if isinstance(ci, str) and ci.strip().isdigit():
                        self.by_cricinfo.setdefault(int(ci), ident)
        wd = wiki.wikidata_cricinfo()
        self.qid_cricinfo: dict[str, int] = {}
        for qid, ci in zip(wd["qid"], wd["cricinfo"]):
            self.qid_cricinfo.setdefault(qid, int(ci))
        self.title_qid = {t: q for q, t in zip(wd["qid"], wd["title"]) if isinstance(t, str)}
        self.wd = wd

    def cricinfo_for(self, page: dict) -> int | None:
        if page.get("qid") and page["qid"] in self.qid_cricinfo:
            return self.qid_cricinfo[page["qid"]]
        m = CRICINFO_RE.search(page.get("text") or "")
        return int(m.group(1)) if m else None

    def resolve_pages(self, pages: dict[str, dict]) -> dict[str, dict]:
        """Annotate wikitext() results with cricinfo and cricsheet ids."""
        for v in pages.values():
            ci = self.cricinfo_for(v)
            v["cricinfo"] = ci
            v["cricsheet_id"] = self.by_cricinfo.get(ci) if ci else None
        return pages

    def resolve_titles(self, titles: Iterable[str]) -> dict[str, dict]:
        return self.resolve_pages(self.wiki.wikitext(titles))


# ---------------------------------------------------------------- parsing
_TEMPLATE_KEEP = {"nowrap", "nobr", "small", "abbr", "sort", "sortname", "flagicon"}


def strip_markup(value: str | None) -> str:
    """Reduce an infobox value to plain text."""
    if not value:
        return ""
    s = re.sub(r"<ref[^>]*/>", "", value)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", ", ", s)
    s = re.sub(r"<[^>]+>", "", s)
    for _ in range(4):  # innermost templates first
        s = re.sub(r"\{\{\s*(?:" + "|".join(_TEMPLATE_KEEP) + r")\s*\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1", s, flags=re.I)
        s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = s.replace("&nbsp;", " ").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip(" ,;")


def infobox(text: str | None, name: str = "Infobox cricketer") -> dict[str, str]:
    """Raw key -> value map of the first matching infobox (values keep markup)."""
    if not text:
        return {}
    m = re.search(r"\{\{\s*" + re.escape(name), text, flags=re.I)
    if not m:
        return {}
    i, depth, start = m.start(), 0, m.start()
    while i < len(text):
        if text.startswith("{{", i):
            depth += 1; i += 2; continue
        if text.startswith("}}", i):
            depth -= 1; i += 2
            if depth == 0:
                break
            continue
        i += 1
    body = text[start + 2:i - 2]
    fields, cur, depth, buf = {}, None, 0, []
    parts, j, last = [], 0, 0
    while j < len(body):  # split on top-level pipes only
        if body.startswith("{{", j) or body.startswith("[[", j):
            depth += 1; j += 2; continue
        if body.startswith("}}", j) or body.startswith("]]", j):
            depth -= 1; j += 2; continue
        if body[j] == "|" and depth == 0:
            parts.append(body[last:j]); last = j + 1
        j += 1
    parts.append(body[last:])
    for part in parts[1:]:
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip().lower()] = v.strip()
    return fields


def html_tables(html: str) -> list[tuple[pd.DataFrame, list[list[str | None]]]]:
    """Parse wikitables with pandas, and for each body row return the article
    title of the first player link in each cell (None where absent)."""
    from lxml import html as lh
    tree = lh.fromstring(html)
    out = []
    for t in tree.xpath("//table[contains(@class,'wikitable')]"):
        markup = lh.tostring(t, encoding="unicode")
        try:
            df = pd.read_html(io.StringIO(markup))[0]
        except ValueError:
            continue
        links = []
        for tr in t.xpath(".//tr[td]"):
            row = []
            for cell in tr.xpath("./td|./th"):
                a = cell.xpath(".//a[starts-with(@href,'/wiki/') and not(contains(@href,':'))]")
                row.append(title_from_url(a[0].get("href")) if a else None)
            links.append(row)
        out.append((df, links))
    return out
