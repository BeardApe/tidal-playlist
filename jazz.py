"""
Wekelijkse Tidal Jazz Playlist Builder: "Ochtendjazz"

Doel: slaperig wakker worden. Zachte, trage cocktailbarjazz, afwisselend
zang en instrumentaal.

Deze versie zoekt niet meer vrij rond via tags en vergelijkbare artiesten.
Dat bracht big band, orkestrale uithalen en atonale piano binnen. In plaats
daarvan kiest het script elke week nummers uit een vaste lijst albums die
van begin tot eind zacht zijn, plus een handvol losse nummers.

Volgorde in de playlist: zang, instrumentaal, zang, instrumentaal, ...

State (state_jazz.json in repo):
  - seen:         {normalized_key: {date, source}}
  - playlist_log: {tidal_id: {date, artist, title, source, genres}}
"""

import os
import json
import random
import requests
import tidalapi
import pylast
from datetime import datetime, timedelta
from pathlib import Path

# Het id uit de Tidal-playlist-URL. Niet geheim, dus gewoon hier.
TIDAL_PLAYLIST_ID     = "efc92d5f-7912-453b-9576-8a63bde1dd29"
LASTFM_API_KEY        = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET     = os.environ["LASTFM_API_SECRET"]
LASTFM_USERNAME       = os.environ["LASTFM_USERNAME"]
LASTFM_PASSWORD_HASH  = pylast.md5(os.environ["LASTFM_PASSWORD"])
SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")

MAX_AGE_DAYS      = 30    # hoe lang een track in de playlist blijft
SEEN_EXPIRY_DAYS  = 120   # daarna mag een track opnieuw gekozen worden
TARGET_ADDITIONS  = 24    # per run: 12 zang + 12 instrumentaal
MAX_PER_ALBUM     = 2     # per run hoogstens zoveel nummers uit hetzelfde album
MIN_DURATION      = 140   # seconden
MAX_DURATION      = 480   # seconden; langer is vaak een uitgesponnen solo

STATE_FILE = Path("state_jazz.json")

# ---------------------------------------------------------------------------
# De vaste lijst: albums die van begin tot eind zacht zijn
# ---------------------------------------------------------------------------

VOCAL_ALBUMS = [
    ("Julie London", "Julie Is Her Name"),
    ("Chet Baker", "Chet Baker Sings"),
    ("Billie Holiday", "Songs for Distingue Lovers"),
    ("Shirley Horn", "Close Enough for Love"),
    ("John Coltrane", "John Coltrane and Johnny Hartman"),
    ("Blossom Dearie", "Blossom Dearie"),
    ("Helen Merrill", "The Nearness of You"),
    ("Jimmy Scott", "Falling in Love Is Wonderful"),
    ("Ella Fitzgerald", "Ella and Louis"),
    ("Peggy Lee", "Black Coffee"),
    ("Chris Connor", "Sings Lullabys of Birdland"),
    ("Astrud Gilberto", "The Astrud Gilberto Album"),
    ("Stacey Kent", "Breakfast on the Morning Tram"),
    ("Melody Gardot", "My One and Only Thrill"),
    ("Madeleine Peyroux", "Careless Love"),
]

INSTRUMENTAL_ALBUMS = [
    ("Bill Evans", "Moon Beams"),
    ("John Coltrane", "Ballads"),
    ("Ben Webster", "Soulville"),
    ("Ben Webster", "Ben Webster Meets Oscar Peterson"),
    ("Coleman Hawkins", "At Ease with Coleman Hawkins"),
    ("Gerry Mulligan", "Night Lights"),
    ("Gerry Mulligan", "Gerry Mulligan Meets Ben Webster"),
    ("Paul Desmond", "Take Ten"),
    ("Chet Baker", "Chet"),
    ("Stan Getz", "Stan Getz Plays"),
    ("Hank Jones", "Steal Away"),
    ("Duke Jordan", "Flight to Denmark"),
]

# Losse nummers van artiesten van wie niet elk album zacht genoeg is.
VOCAL_PICKS = [
    ("Gregory Porter", "Hey Laura"),
    ("Gregory Porter", "Be Good (Lion's Song)"),
    ("Gregory Porter", "No Love Dying"),
    ("Gregory Porter", "Water Under Bridges"),
    ("Louis Armstrong", "A Kiss to Build a Dream On"),
]

INSTRUMENTAL_PICKS = [
    ("Miles Davis", "Blue in Green"),
    ("Miles Davis", "Flamenco Sketches"),
    ("Coleman Hawkins", "Body and Soul"),
]

# Nummers die op een verder zacht album toch te veel swingen.
SKIP_TITLES = {
    "who's got rhythm", "the cat walk", "no problem", "day in day out",
    "why shouldn't i", "festival minor",
}


def is_skipped(title: str) -> bool:
    t = title.lower().replace("\u2019", "'")
    return any(t.startswith(x) for x in SKIP_TITLES)


# Last.fm-tags die op tempo, uithalen of dissonantie wijzen. Meer van deze
# tags dan zachte tags, en het nummer valt af. Vangt de uitschieter op een
# verder zacht album.
SLOW_TAGS = {
    "ballad", "ballads", "slow", "mellow", "smooth", "soft", "quiet",
    "torch song", "late night", "romantic", "melancholy", "relaxing",
    "chill", "jazz ballad", "bossa nova",
}
FAST_TAGS = {
    "uptempo", "up-tempo", "fast", "swing", "swinging", "bebop", "hard bop",
    "big band", "orchestral", "intense", "dramatic", "energetic", "dance",
    "free jazz", "avant-garde", "atonal", "experimental", "live", "funky",
}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"seen": {}, "playlist_log": {}}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"[State] Opgeslagen: {len(state['seen'])} geziene tracks, "
          f"{len(state['playlist_log'])} in playlist_log")


def normalize_key(artist: str, title: str) -> str:
    return f"{artist.strip().lower()}|{title.strip().lower()}"


def load_tidal_session() -> tidalapi.Session:
    session = tidalapi.Session()
    session.load_session_from_file(Path("/tmp/tidal_session.json"))
    return session


def get_lastfm_network() -> pylast.LastFMNetwork:
    return pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET,
        username=LASTFM_USERNAME, password_hash=LASTFM_PASSWORD_HASH,
    )


# ---------------------------------------------------------------------------
# Genres, zoals bij Nachtradio: eerst Spotify, anders de Last.fm-tags
# van de artiest. Per artiest één keer opgezocht.
# ---------------------------------------------------------------------------

def get_spotify_token() -> str:
    if not SPOTIFY_CLIENT_ID:
        return ""
    try:
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        print(f"[Spotify] Token mislukt: {e}")
        return ""


def spotify_genres(token: str, artist_name: str) -> list:
    if not token:
        return []
    try:
        resp = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": artist_name, "type": "artist", "limit": 1},
            timeout=10,
        )
        if resp.status_code == 200:
            items = resp.json().get("artists", {}).get("items", [])
            if items and items[0]["name"].lower() == artist_name.lower():
                return items[0].get("genres", [])
    except Exception:
        pass
    return []


def lastfm_artist_tags(network, artist_name: str) -> list:
    try:
        tags = network.get_artist(artist_name).get_top_tags(limit=6)
        return [str(t.item.get_name()).lower().replace("-", " ") for t in tags]
    except Exception:
        return []


class GenreLookup:
    def __init__(self, network):
        self.network = network
        self.token = get_spotify_token()
        self.cache = {}

    def get(self, artist_name: str) -> list:
        key = artist_name.strip().lower()
        if key not in self.cache:
            genres = spotify_genres(self.token, artist_name)
            if not genres:
                genres = lastfm_artist_tags(self.network, artist_name)
            self.cache[key] = genres[:4]
        return self.cache[key]


def backfill_genres(state: dict, lookup: GenreLookup):
    """Vult ontbrekende genres aan, ook voor alles wat al eerder binnenkwam."""
    filled = 0
    for entry in state["playlist_log"].values():
        if isinstance(entry, dict) and not entry.get("genres") and entry.get("artist"):
            entry["genres"] = lookup.get(entry["artist"])
            filled += 1
    for key, entry in state["seen"].items():
        if not isinstance(entry, dict) or entry.get("genres"):
            continue
        artist = entry.get("artist") or key.split("|")[0]
        if artist:
            entry["genres"] = lookup.get(artist)
            filled += 1
    print(f"[Genres] {filled} tracks aangevuld")


def too_lively(network: pylast.LastFMNetwork, artist: str, title: str) -> bool:
    try:
        tags = network.get_track(artist, title).get_top_tags(limit=12)
    except Exception:
        return False
    score = 0
    for item in tags:
        name = str(item.item.name).lower()
        if name in SLOW_TAGS:
            score += 1
        if name in FAST_TAGS:
            score -= 1
    return score < 0


def find_album(session: tidalapi.Session, artist: str, title: str):
    try:
        results = session.search(f"{artist} {title}", models=[tidalapi.album.Album], limit=8)
        albums = results.get("albums", [])
        start = title.lower()[:12]
        for album in albums:
            if start in album.name.lower() and artist.lower() in album.artist.name.lower():
                return album
        for album in albums:
            if start in album.name.lower():
                return album
    except Exception as e:
        print(f"  [Tidal] Zoekfout album '{artist} {title}': {e}")
    return None


def find_track(session: tidalapi.Session, artist: str, title: str):
    try:
        results = session.search(f"{artist} {title}", models=[tidalapi.media.Track], limit=5)
        for track in results.get("tracks", []):
            if artist.lower() in track.artist.name.lower():
                return track
    except Exception as e:
        print(f"  [Tidal] Zoekfout '{artist} {title}': {e}")
    return None


def build_pool(session, albums, picks, label) -> list:
    """Alle kandidaat-tracks van één soort (zang of instrumentaal)."""
    pool = []
    for artist, album_title in albums:
        album = find_album(session, artist, album_title)
        if not album:
            print(f"  ✗ Album niet gevonden: {artist} / {album_title}")
            continue
        try:
            for track in album.tracks():
                pool.append({"track": track, "artist": track.artist.name,
                             "title": track.name, "group": album_title, "kind": label,
                             "source": f"Album~{album_title}"})
        except Exception as e:
            print(f"  [Tidal] Tracks ophalen mislukt voor {album_title}: {e}")
    for artist, title in picks:
        track = find_track(session, artist, title)
        if track:
            pool.append({"track": track, "artist": track.artist.name,
                         "title": track.name, "group": f"pick:{artist}", "kind": label,
                         "source": f"Pick~{artist}"})
    random.shuffle(pool)
    print(f"[Pool] {label}: {len(pool)} kandidaten")
    return pool


def cleanup_playlist(session, playlist_id: str, playlist_log: dict) -> dict:
    """
    Haalt twee soorten tracks weg:
      - ouder dan MAX_AGE_DAYS
      - niet afkomstig uit de vaste lijst (alles van de vorige, vrije versie)
    """
    cutoff = (datetime.now() - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    try:
        tidal_ids = [str(t.id) for t in session.playlist(playlist_id).tracks()]
        to_remove = []
        for i, tid in enumerate(tidal_ids):
            entry = playlist_log.get(tid)
            if not isinstance(entry, dict):
                to_remove.append(i)
                continue
            source = entry.get("source", "")
            if not (source.startswith("Album~") or source.startswith("Pick~")):
                to_remove.append(i)
            elif is_skipped(entry.get("title", "")):
                to_remove.append(i)
            elif entry.get("date", "9999-12-31") < cutoff:
                to_remove.append(i)
        for idx in sorted(to_remove, reverse=True):
            session.playlist(playlist_id).remove_by_index(idx)
        for idx in to_remove:
            playlist_log.pop(tidal_ids[idx], None)
        print(f"[Tidal] {len(to_remove)} tracks verwijderd")
    except Exception as e:
        print(f"[Tidal] Opruimen mislukt: {e}")
    return playlist_log


def prune_seen(seen: dict) -> dict:
    cutoff = (datetime.now() - timedelta(days=SEEN_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    return {k: v for k, v in seen.items()
            if (v.get("date", "") if isinstance(v, dict) else (v or "")) >= cutoff}


def next_ok(pool, network, seen, existing_ids, per_group):
    """Geeft de volgende bruikbare kandidaat uit de pool terug, of None."""
    while pool:
        c = pool.pop()
        track = c["track"]
        key = normalize_key(c["artist"], c["title"])
        tid = str(track.id)
        duration = getattr(track, "duration", 0) or 0
        if key in seen or tid in existing_ids or is_skipped(c["title"]):
            continue
        if per_group.get(c["group"], 0) >= MAX_PER_ALBUM:
            continue
        if duration and not (MIN_DURATION <= duration <= MAX_DURATION):
            continue
        if too_lively(network, c["artist"], c["title"]):
            print(f"  ✗ {c['artist']} / {c['title']} (te levendig volgens tags)")
            continue
        return c
    return None


def main():
    print(f"\n{'='*50}")
    print(f"  Ochtendjazz update, {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    state        = load_state()
    seen         = prune_seen(state["seen"])
    playlist_log = state["playlist_log"]

    session = load_tidal_session()
    print("[Tidal] Ingelogd ✓\n")
    network = get_lastfm_network()
    lookup  = GenreLookup(network)

    playlist_log = cleanup_playlist(session, TIDAL_PLAYLIST_ID, playlist_log)
    existing_ids = {str(t.id) for t in session.playlist(TIDAL_PLAYLIST_ID).tracks()}

    vocal = build_pool(session, VOCAL_ALBUMS, VOCAL_PICKS, "zang")
    instr = build_pool(session, INSTRUMENTAL_ALBUMS, INSTRUMENTAL_PICKS, "instrumentaal")

    today = datetime.now().strftime("%Y-%m-%d")
    added, per_group, turn = [], {}, 0
    while len(added) < TARGET_ADDITIONS and (vocal or instr):
        pool = vocal if turn % 2 == 0 else instr
        turn += 1
        c = next_ok(pool, network, seen, existing_ids, per_group)
        if not c:
            continue
        track = c["track"]
        tid = str(track.id)
        added.append(track)
        existing_ids.add(tid)
        per_group[c["group"]] = per_group.get(c["group"], 0) + 1
        genres = lookup.get(c["artist"])
        seen[normalize_key(c["artist"], c["title"])] = {
            "date": today, "source": c["source"], "artist": c["artist"],
            "title": c["title"], "kind": c["kind"], "genres": genres}
        playlist_log[tid] = {"date": today, "artist": c["artist"], "title": c["title"],
                             "source": c["source"], "kind": c["kind"], "genres": genres}
        print(f"  ✓ [{c['source']}] {c['artist']} / {c['title']}")

    if added:
        session.playlist(TIDAL_PLAYLIST_ID).add([t.id for t in added])
        print(f"\n[Tidal] {len(added)} tracks toegevoegd ✓")
    else:
        print("\n[Tidal] Geen nieuwe tracks gevonden.")

    state["seen"], state["playlist_log"] = seen, playlist_log
    backfill_genres(state, lookup)
    save_state(state)


if __name__ == "__main__":
    main()
