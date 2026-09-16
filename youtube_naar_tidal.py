"""
youtube_naar_tidal.py — Zet de tracklist van een YouTube-video, of van alle video's in een
YouTube-playlist, om naar één Tidal-playlist zonder dubbels.

Wat dit doet:
1. Haalt titel en beschrijving van de YouTube-video op via de YouTube Data API (gratis sleutel, zie hieronder)
2. Pikt de tracklist eruit, op twee manieren:
   - de "Muziek in deze video"-strook (de horizontale kaartjes onder de beschrijving)
   - regels in de beschrijving zoals "00:00 Artiest - Titel", "1. Artiest – Titel" of "Artiest - Titel [Label]"
3. Zoekt elke track op in Tidal
4. Maakt een nieuwe Tidal-playlist met de naam van de video, of vult een bestaande aan (zonder dubbels)
5. Print op het einde wat niet gevonden werd

Nodig: een YouTube Data API-sleutel in de omgevingsvariabele YOUTUBE_API_KEY
(in GitHub Actions: secret YOUTUBE_API_KEY). Zonder sleutel probeert het script de
pagina zelf te lezen, maar dat blokkeert YouTube soms op servers.

Lokaal uitvoeren (Windows):
    set YOUTUBE_API_KEY=jouw_sleutel
    python youtube_naar_tidal.py https://www.youtube.com/watch?v=XXXX
    python youtube_naar_tidal.py https://www.youtube.com/playlist?list=PLXXXX     (alle video's ineens)

Wil je de tracks in een bestaande playlist zetten? Geef het Tidal-ID mee als tweede argument:
    python youtube_naar_tidal.py https://www.youtube.com/watch?v=XXXX efc92d5f-7912-453b-9576-8a63bde1dd29

Via GitHub Actions: zie youtube_naar_tidal.yml (handmatig starten, link invullen, klaar).
"""

import os
import re
import sys
import time
from pathlib import Path

import json

import requests
import tidalapi

# Waar de Tidal-sessie staat: lokaal session.json, in GitHub Actions /tmp/tidal_session.json
SESSION_PATHS = [Path("session.json"), Path("/tmp/tidal_session.json")]


# ── YouTube ──────────────────────────────────────────────────────
def video_id(url: str) -> str:
    """Haalt het video-ID uit een YouTube-link, ook als er &list=... achter hangt."""
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise RuntimeError(f"Geen YouTube-video-ID gevonden in: {url}")
    return m.group(1)


_html_cache: dict[str, str] = {}


def fetch_watch_html(vid: str) -> str:
    """Haalt de HTML van de videopagina op (één keer, daarna uit cache). Leeg als het mislukt."""
    if vid not in _html_cache:
        try:
            resp = requests.get(
                f"https://www.youtube.com/watch?v={vid}&hl=en",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                         "Accept-Language": "en"},
                cookies={"CONSENT": "YES+1", "SOCS": "CAI"},   # anders krijg je in Europa de cookiemuur
                timeout=15,
            )
            _html_cache[vid] = resp.text if resp.ok else ""
        except requests.RequestException:
            _html_cache[vid] = ""
    return _html_cache[vid]


def _json_var(html: str, name: str) -> dict:
    """Vist een JSON-blok als 'ytInitialData = {...};' uit de pagina."""
    m = re.search(name + r"\s*=\s*(\{.*?\});\s*(?:</script>|var )", html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def _api(endpoint: str, **params) -> dict:
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Voor een YouTube-playlist is een API-sleutel nodig. Zet YOUTUBE_API_KEY (zie bovenaan dit script).")
    r = requests.get(f"https://www.googleapis.com/youtube/v3/{endpoint}", params={**params, "key": api_key}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube API gaf fout {r.status_code}: {r.text[:300]}")
    return r.json()


def playlist_id(url: str) -> str:
    """Geeft het playlist-ID als de link een echte YouTube-playlist is (PL..., niet een 'Mix' RD...)."""
    m = re.search(r"[?&]list=(PL[A-Za-z0-9_-]+|UU[A-Za-z0-9_-]+|OL[A-Za-z0-9_-]+)", url)
    return m.group(1) if m and "playlist?" in url else ""


def get_playlist_videos(plid: str) -> tuple[str, list[str]]:
    """Titel van de YouTube-playlist en alle video-ID's erin, in volgorde."""
    info = _api("playlists", part="snippet", id=plid).get("items", [])
    title = info[0]["snippet"]["title"] if info else plid
    vids, token = [], None
    while True:
        page = _api("playlistItems", part="contentDetails", playlistId=plid, maxResults=50, pageToken=token)
        vids += [it["contentDetails"]["videoId"] for it in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            break
    return title, vids


def get_youtube_info(vid: str) -> tuple[str, str]:
    """Titel en beschrijving. Eerst via de YouTube Data API (betrouwbaar), anders uit de pagina."""
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if api_key:
        r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                         params={"part": "snippet", "id": vid, "key": api_key}, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"YouTube API gaf fout {r.status_code}: {r.text[:300]}")
        items = r.json().get("items", [])
        if not items:
            raise RuntimeError(f"YouTube API kent video {vid} niet (privé, verwijderd of fout ID?)")
        s = items[0]["snippet"]
        return s.get("title", vid), s.get("description", "")

    details = _json_var(fetch_watch_html(vid), "ytInitialPlayerResponse").get("videoDetails", {})
    if not details.get("title"):
        raise RuntimeError("Kon de video niet lezen zonder API-sleutel. Zet YOUTUBE_API_KEY (zie bovenaan dit script).")
    return details["title"], details.get("shortDescription", "")


def get_music_section(vid: str) -> list[dict]:
    """Leest de 'Muziek in deze video'-kaartjes uit de pagina (de horizontale strook).
    Die staan niet in de gewone beschrijving en ook niet in de API, alleen in de paginadata.
    YouTube gebruikt twee opmaken voor die kaartjes; allebei worden hier herkend."""
    html = fetch_watch_html(vid)
    if not html:
        print("  (kon de videopagina niet ophalen, muziekstrook overgeslagen)")
        return []
    data = _json_var(html, "ytInitialData")
    if not data:
        print(f"  (geen paginadata gevonden in {len(html)} tekens HTML, muziekstrook overgeslagen)")
        return []

    tracks = []

    def text(node) -> str:
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            if "simpleText" in node:
                return node["simpleText"]
            if "runs" in node:
                return "".join(r.get("text", "") for r in node["runs"])
            if "content" in node:
                return text(node["content"])
        return ""

    def walk(node):
        if isinstance(node, dict):
            # nieuwe opmaak: kaartje met titel (nummer), subtitel (artiest), tweede subtitel (album)
            if "videoAttributeViewModel" in node:
                vm = node["videoAttributeViewModel"]
                song, artist = text(vm.get("title")).strip(), text(vm.get("subtitle")).strip()
                if song and artist:
                    tracks.append({"artist": artist.split(",")[0].strip(), "title": song})
                return
            # oude opmaak: rijen met SONG / ARTIST / ALBUM
            if "infoRows" in node:
                song = artist = ""
                for row in node["infoRows"]:
                    r = row.get("infoRowRenderer", {})
                    label = text(r.get("title")).strip().upper()
                    value = text(r.get("defaultMetadata") or r.get("expandedMetadata")).strip()
                    if label in ("SONG", "NUMMER"):
                        song = value
                    elif label in ("ARTIST", "ARTIEST"):
                        artist = value
                if song and artist:
                    tracks.append({"artist": artist.split(",")[0].strip(), "title": song})
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return tracks


# Wat vooraan een regel mag staan en genegeerd wordt: tijdcodes, nummering, streepjes, bullets
PREFIX = re.compile(
    r"^\s*[\(\[]?\d{1,2}:\d{2}(?::\d{2})?[\)\]]?\s*[-–—:]?\s*"   # 00:00 of (1:02:33)
    r"|^\s*\d{1,3}\s*[.)\-:]\s*"                                  # 1. of 12)
    r"|^\s*[-–—•*▪●]\s*"                                          # bullets
)
SPLIT = re.compile(r"\s+[-–—]\s+")   # scheiding artiest/titel
JUNK  = re.compile(r"subscribe|follow|instagram|facebook|tiktok|http|www\.|thanks|bedankt|merci|recorded|mixed by|tracklist", re.I)


def parse_tracklist(description: str) -> list[dict]:
    """Zoekt regels met 'Artiest - Titel' in de beschrijving. Geeft lijst van {'artist', 'title'}."""
    tracks = []
    for raw in description.splitlines():
        line = raw.strip()
        if not line or JUNK.search(line):
            continue
        # prefixen wegknippen, eventueel meerdere na elkaar ("1. 00:00 Artiest - Titel")
        prev = None
        while prev != line:
            prev, line = line, PREFIX.sub("", line, count=1)
        # labels en opmerkingen tussen haakjes achteraan weg: "[Ninja Tune]" "(1998)"
        line = re.sub(r"\s*[\[\(][^\]\)]*[\]\)]\s*$", "", line).strip()

        parts = SPLIT.split(line, maxsplit=1)
        if len(parts) != 2:
            continue
        artist, title = parts[0].strip(" \"'"), parts[1].strip(" \"'")
        # onbekende tracks ("ID - ID", "??? - ???") overslaan
        if not artist or not title or re.fullmatch(r"(id|\?+|unknown|unreleased)", artist, re.I) \
                or re.fullmatch(r"(id|\?+|unknown|unreleased)", title, re.I):
            continue
        if len(artist) > 60 or len(title) > 100:   # dat is geen track, dat is een zin
            continue
        # "feat." uit de artiestnaam halen, dat zoekt beter
        artist = re.split(r"\s+(?:feat\.?|ft\.?|featuring|&|x|,)\s+", artist, maxsplit=1, flags=re.I)[0]
        tracks.append({"artist": artist, "title": title})
    return tracks


# ── Tidal ────────────────────────────────────────────────────────
def load_tidal_session() -> tidalapi.Session:
    for path in SESSION_PATHS:
        if path.exists():
            session = tidalapi.Session()
            session.load_session_from_file(path)
            if session.check_login():
                return session
    raise RuntimeError("Geen geldige Tidal-sessie gevonden. Voer eerst 'python setup.py' uit.")


def clean(text: str) -> str:
    """Maakt titels vergelijkbaar: kleine letters, geen '(Remastered 2004)' of '- Live'."""
    text = re.sub(r"\(.*?\)|\[.*?\]|\s-\s.*$", "", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def search_tidal_track(session: tidalapi.Session, artist: str, title: str):
    """Zoekt de track in Tidal. Geeft voorkeur aan een match op artiest én titel."""
    try:
        results = session.search(f"{artist} {title}", models=[tidalapi.media.Track], limit=10)
    except Exception as e:
        print(f"  [Tidal] Zoekfout '{artist} - {title}': {e}")
        return None

    candidates = results.get("tracks", [])
    want_artist, want_title = clean(artist), clean(title)

    # 1. artiest en titel kloppen allebei
    for t in candidates:
        if want_title == clean(t.name) and (want_artist in clean(t.artist.name) or clean(t.artist.name) in want_artist):
            return t
    # 2. artiest klopt
    for t in candidates:
        if want_artist in clean(t.artist.name) or clean(t.artist.name) in want_artist:
            return t
    return None


# ── Hoofdprogramma ───────────────────────────────────────────────
def main():
    youtube_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("YOUTUBE_URL", "")
    tidal_id    = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("TIDAL_PLAYLIST_ID", "").strip()
    if not youtube_url:
        sys.exit("Geef een YouTube-link mee: python youtube_naar_tidal.py https://www.youtube.com/watch?v=XXXX")

    plid = playlist_id(youtube_url)
    if plid:
        print("YouTube-playlist lezen...")
        playlist_name, vids = get_playlist_videos(plid)
        print(f"  '{playlist_name}': {len(vids)} video's\n")
    else:
        vids = [video_id(youtube_url)]
        playlist_name = ""

    # tracks van alle video's verzamelen, zonder dubbels
    yt_tracks, seen = [], set()
    for n, vid in enumerate(vids, 1):
        try:
            video_title, description = get_youtube_info(vid)
        except RuntimeError as e:
            print(f"  [{n}/{len(vids)}] overgeslagen: {e}")
            continue
        from_cards = get_music_section(vid)
        from_text  = parse_tracklist(description)
        nieuw = 0
        # eerst de kaartjes (die zijn het betrouwbaarst), dan de tekst
        for tr in from_cards + from_text:
            key = clean(tr["artist"]) + "|" + clean(tr["title"])
            if key not in seen:
                seen.add(key)
                yt_tracks.append(tr)
                nieuw += 1
        print(f"  [{n}/{len(vids)}] '{video_title}': {len(from_cards)} in de muziekstrook, "
              f"{len(from_text)} in de beschrijving, {nieuw} nieuw")
        if not playlist_name:
            playlist_name = video_title
        time.sleep(0.5)
    print(f"\n{len(yt_tracks)} unieke tracks gevonden\n")
    if not yt_tracks:
        sys.exit("Geen tracklist gevonden, niet in de muziekstrook en niet in de beschrijving.")

    print("Inloggen bij Tidal...")
    session = load_tidal_session()
    if tidal_id:
        playlist = session.playlist(tidal_id)
        existing = {str(t.id) for t in playlist.tracks()}
        print(f"  Playlist '{playlist.name}' heeft al {len(existing)} tracks\n")
    else:
        playlist = session.user.create_playlist(playlist_name[:100], f"Tracklist uit {youtube_url}")
        existing = set()
        print(f"  Nieuwe playlist gemaakt: '{playlist.name}'\n")

    to_add, not_found = [], []
    for i, tr in enumerate(yt_tracks, 1):
        label = f"{tr['artist']} - {tr['title']}"
        found = search_tidal_track(session, tr["artist"], tr["title"])
        if not found:
            print(f"  [{i:>2}] ✗ niet gevonden: {label}")
            not_found.append(label)
        elif str(found.id) in existing:
            print(f"  [{i:>2}] = staat er al:   {label}")
        else:
            print(f"  [{i:>2}] ✓ {found.artist.name} - {found.name}")
            to_add.append(found.id)
            existing.add(str(found.id))
        time.sleep(0.3)   # Tidal niet overvragen

    if to_add:
        for start in range(0, len(to_add), 50):
            playlist.add(to_add[start:start + 50])
        print(f"\n✓ {len(to_add)} tracks toegevoegd aan '{playlist.name}'")
    else:
        print("\nNiets toe te voegen.")

    if not_found:
        print(f"\n{len(not_found)} tracks niet gevonden op Tidal:")
        for label in not_found:
            print(f"  - {label}")


if __name__ == "__main__":
    main()
