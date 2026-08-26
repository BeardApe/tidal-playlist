"""
Wekelijkse Tidal Jazz Playlist Builder — "Ochtendjazz"

Zelfde opzet als main.py, maar afgestemd op zachte, trage, nostalgische jazz.
Drie verschillen met de indie-versie, allemaal omdat het repertoire historisch is
in plaats van nieuw:

  1. Bronnen zijn Last.fm-tags en seed-artiesten, niet de radio-playlists van
     Spotify. Er verschijnt geen nieuwe Billie Holiday meer, dus zoeken we in
     het bestaande repertoire in plaats van in wekelijkse nieuwe releases.
  2. Genres worden op een toelatingslijst getoetst, niet alleen op een
     blokkeerlijst. Alles wat niet als zachte jazz herkend wordt, valt af.
  3. Tracks mogen na SEEN_EXPIRY_DAYS terugkeren. Klassiekers wil je opnieuw
     horen; dat is bij nieuwe indie niet zo.

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
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]

MAX_AGE_DAYS      = 30    # hoe lang een track in de playlist blijft
SEEN_EXPIRY_DAYS  = 180   # daarna mag een track opnieuw gekozen worden
TARGET_ADDITIONS  = 25    # hoeveel nieuwe tracks per run maximaal
MIN_DURATION      = 140   # seconden; korter is meestal een snel 78-toeren nummer
MAX_DURATION      = 720   # seconden; langer is meestal een live-uitgesponnen solo

STATE_FILE = Path("state_jazz.json")

# ---------------------------------------------------------------------------
# Smaakfilters
# ---------------------------------------------------------------------------

# Een artiest moet minstens één van deze genres hebben, anders valt hij af.
ALLOWED_GENRES = {
    "jazz", "vocal jazz", "cool jazz", "west coast jazz", "chamber jazz",
    "jazz standard", "torch", "traditional pop", "adult standards",
    "bossa nova", "samba jazz", "lounge", "easy listening", "crooner",
    "piano jazz", "contemporary post-bop", "ecm",
}

# Deze genres vliegen er altijd uit, ook als er "jazz" bij staat.
BLOCKED_GENRES = {
    "bebop", "hard bop", "free jazz", "avant-garde jazz", "avant-garde",
    "free improvisation", "noise", "experimental",
    "big band", "swing revival", "electro swing", "gypsy jazz",
    "dixieland", "ragtime", "boogie-woogie",
    "smooth jazz", "jazz fusion", "fusion", "jazz funk", "acid jazz",
    "nu jazz", "jazz rap", "afrobeat", "salsa", "mambo",
    "rap", "hip hop", "edm", "house", "techno", "metal", "punk",
}

# Last.fm-tags die op een traag, zacht nummer wijzen (pluspunten).
SLOW_TAGS = {
    "ballad", "ballads", "slow", "mellow", "smooth", "soft", "quiet",
    "vocal jazz", "cool jazz", "torch song", "torch songs", "late night",
    "lounge", "romantic", "melancholy", "melancholic", "sad", "intimate",
    "relaxing", "chill", "jazz ballad", "bossa nova", "nocturne",
}

# Last.fm-tags die op tempo of dissonantie wijzen (minpunten).
FAST_TAGS = {
    "uptempo", "up-tempo", "fast", "swing", "swinging", "bebop", "hard bop",
    "big band", "jump blues", "boogie", "dance", "party", "energetic",
    "free jazz", "avant-garde", "atonal", "experimental", "dissonant",
    "live", "jam", "funky", "groovy", "latin jazz",
}

BLOCKED_ARTISTS = {
    "kenny g", "dave koz", "boney james", "spyro gyra", "the rippingtons",
    "michael buble", "michael bublé", "jamie cullum", "postmodern jukebox",
    "caro emerald", "parov stelar", "avishai cohen", "shai maestro",
    "omer avital", "anat cohen", "norah jones", "diana krall",
}

# Artiesten die je hoe dan ook wil, ook als hun genre op de blokkeerlijst staat.
# De tempotoets op tags blijft wel gelden, dus je krijgt alleen hun trage werk.
ALLOWED_ARTISTS = {
    "gregory porter",
}

# Last.fm-tags die als radiozender dienen: elke week een greep uit de top.
LASTFM_TAGS = [
    "vocal jazz", "cool jazz", "jazz ballad", "torch song",
    "west coast jazz", "bossa nova", "chamber jazz", "traditional pop",
]

SEED_ARTISTS = [
    # Zang, de kern van de smaak
    "Billie Holiday", "Shirley Horn", "Julie London", "Blossom Dearie",
    "Helen Merrill", "Jimmy Scott", "Johnny Hartman", "Chris Connor",
    "June Christy", "Jeri Southern", "Peggy Lee", "Carmen McRae",
    "Nat King Cole", "Dinah Washington", "Sarah Vaughan", "Etta Jones",
    "Abbey Lincoln", "Nina Simone", "Astrud Gilberto", "João Gilberto",
    # Hedendaags maar in dezelfde toon
    "Melody Gardot", "Stacey Kent", "Madeleine Peyroux",
    "Cécile McLorin Salvant", "Sara Gazarek", "Cyrille Aimée",
    "Gregory Porter",
    # Blazers, zacht en lyrisch
    "Chet Baker", "Stan Getz", "Ben Webster", "Lester Young",
    "Paul Desmond", "Gerry Mulligan", "Art Pepper", "Lee Konitz",
    "Coleman Hawkins", "Ibrahim Maalouf", "Erik Truffaz", "Enrico Rava",
    # Piano en snaren
    "Bill Evans", "Ahmad Jamal", "Duke Jordan", "Hank Jones",
    "Tommy Flanagan", "Kenny Barron", "Fred Hersch", "Bill Charlap",
    "Tord Gustavsen", "Bobo Stenson", "Jim Hall", "Wes Montgomery",
    "Charlie Haden", "Marc Johnson", "Django Reinhardt",
]


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


def clean_title(title: str) -> str:
    """Haalt live- en remasteraanduidingen weg zodat dubbels beter opvallen."""
    lowered = title.lower()
    for marker in (" - live", "(live", " - remaster", "(remaster",
                   " - mono", " - stereo", " - take "):
        idx = lowered.find(marker)
        if idx > 0:
            return title[:idx].strip()
    return title.strip()


def load_tidal_session() -> tidalapi.Session:
    session = tidalapi.Session()
    session.load_session_from_file(Path("/tmp/tidal_session.json"))
    return session


def get_lastfm_network() -> pylast.LastFMNetwork:
    return pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET,
        username=LASTFM_USERNAME, password_hash=LASTFM_PASSWORD_HASH,
    )


def get_spotify_token() -> str:
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def lookup_genres_by_name(token: str, artist_name: str) -> list[str]:
    """Zoekt een artiest op naam in Spotify en geeft de genres terug."""
    try:
        resp = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": artist_name, "type": "artist", "limit": 1},
            timeout=10,
        )
        if resp.status_code == 200:
            items = resp.json().get("artists", {}).get("items", [])
            if items:
                return items[0].get("genres", [])
    except Exception:
        pass
    return []


def genre_verdict(genres: list[str]) -> str:
    """
    Geeft 'blocked', 'allowed' of 'onbekend' terug.
    Onbekend gebeurt bij artiesten die Spotify geen genres geeft; die laten we
    door en beoordelen we verderop alleen op Last.fm-tags.
    """
    lowered = [g.lower() for g in genres]
    for g in lowered:
        for blocked in BLOCKED_GENRES:
            if blocked in g:
                return "blocked"
    for g in lowered:
        for allowed in ALLOWED_GENRES:
            if allowed in g:
                return "allowed"
    return "onbekend" if not lowered else "blocked"


def tag_score(network: pylast.LastFMNetwork, artist: str, title: str) -> int:
    """
    Telt de Last.fm-tags van één track: +1 per trage tag, -1 per snelle tag.
    Dit vervangt de tempodata van Spotify, die sinds november 2024 dicht is.
    """
    try:
        tags = network.get_track(artist, title).get_top_tags(limit=12)
    except Exception:
        return 0
    score = 0
    for item in tags:
        name = str(item.item.name).lower()
        if name in SLOW_TAGS:
            score += 1
        if name in FAST_TAGS:
            score -= 1
    return score


def get_tag_radio(network: pylast.LastFMNetwork, per_tag: int = 12) -> list[dict]:
    """Haalt per Last.fm-tag een willekeurige greep uit de populairste tracks."""
    tracks = []
    for tag_name in random.sample(LASTFM_TAGS, min(4, len(LASTFM_TAGS))):
        try:
            top = network.get_tag(tag_name).get_top_tracks(limit=60)
            for item in random.sample(top, min(per_tag, len(top))):
                tracks.append({
                    "artist": str(item.item.artist.name),
                    "title":  str(item.item.title),
                    "source": f"Tag~{tag_name}",
                })
            print(f"[Last.fm] Tag '{tag_name}': {per_tag} gekozen")
        except Exception as e:
            print(f"[Last.fm] Fout bij tag {tag_name}: {e}")
    return tracks


def get_seed_tracks(network: pylast.LastFMNetwork, n_artists: int = 6,
                    per_artist: int = 4) -> list[dict]:
    """Populairste tracks van de seed-artiesten zelf: de klassiekers."""
    tracks = []
    for name in random.sample(SEED_ARTISTS, min(n_artists, len(SEED_ARTISTS))):
        try:
            top = network.get_artist(name).get_top_tracks(limit=25)
            for item in random.sample(top, min(per_artist, len(top))):
                tracks.append({
                    "artist": name,
                    "title":  str(item.item.title),
                    "source": f"Seed~{name}",
                })
        except Exception as e:
            print(f"[Last.fm] Fout bij seed {name}: {e}")
    print(f"[Last.fm] {len(tracks)} tracks van seed-artiesten")
    return tracks


def get_similar_discoveries(network: pylast.LastFMNetwork, n_artists: int = 5,
                            per_artist: int = 3) -> list[dict]:
    """Ontdekkingen via vergelijkbare artiesten, zoals in de indie-versie."""
    tracks = []
    for seed_name in random.sample(SEED_ARTISTS, min(n_artists, len(SEED_ARTISTS))):
        try:
            similar = network.get_artist(seed_name).get_similar(limit=10)
            for sim_item in random.sample(similar, min(2, len(similar))):
                sim_artist = sim_item.item
                top = sim_artist.get_top_tracks(limit=12)
                for item in random.sample(top, min(per_artist, len(top))):
                    tracks.append({
                        "artist": str(sim_artist.name),
                        "title":  str(item.item.title),
                        "source": f"LastFM~{seed_name}",
                    })
        except Exception as e:
            print(f"[Last.fm] Fout bij {seed_name}: {e}")
    print(f"[Last.fm] {len(tracks)} ontdekkingen via vergelijkbare artiesten")
    return tracks


def search_tidal_track(session: tidalapi.Session, artist: str, title: str):
    try:
        results = session.search(f"{artist} {title}", models=[tidalapi.media.Track], limit=5)
        tracks  = results.get("tracks", [])
        for track in tracks:
            if (artist.lower() in track.artist.name.lower() or
                    track.artist.name.lower() in artist.lower()):
                return track
        return tracks[0] if tracks else None
    except Exception as e:
        print(f"  [Tidal] Zoekfout '{artist} {title}': {e}")
        return None


def get_existing_tidal_ids(session: tidalapi.Session, playlist_id: str) -> set:
    try:
        return {str(t.id) for t in session.playlist(playlist_id).tracks()}
    except Exception as e:
        print(f"[Tidal] Kon bestaande tracks niet ophalen: {e}")
        return set()


def remove_old_tracks(session: tidalapi.Session, playlist_id: str, playlist_log: dict) -> dict:
    cutoff = (datetime.now() - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    try:
        tracks    = list(session.playlist(playlist_id).tracks())
        tidal_ids = [str(t.id) for t in tracks]

        def get_date(tid):
            e = playlist_log.get(tid)
            if isinstance(e, dict):
                return e.get("date", "9999-12-31")
            return e or "9999-12-31"

        indices_to_remove = [i for i, tid in enumerate(tidal_ids) if get_date(tid) < cutoff]

        if indices_to_remove:
            for idx in sorted(indices_to_remove, reverse=True):
                session.playlist(playlist_id).remove_by_index(idx)
            for idx in indices_to_remove:
                playlist_log.pop(tidal_ids[idx], None)
            print(f"[Tidal] {len(indices_to_remove)} tracks verwijderd (ouder dan {MAX_AGE_DAYS}d)")
        else:
            print(f"[Tidal] Geen tracks ouder dan {MAX_AGE_DAYS} dagen")
    except Exception as e:
        print(f"[Tidal] Rotatie mislukt: {e}")
    return playlist_log


def prune_seen(seen: dict) -> dict:
    """Vergeet tracks die lang genoeg geleden zijn, zodat ze mogen terugkeren."""
    cutoff = (datetime.now() - timedelta(days=SEEN_EXPIRY_DAYS)).strftime("%Y-%m-%d")
    before = len(seen)
    kept = {}
    for key, entry in seen.items():
        date = entry.get("date", "") if isinstance(entry, dict) else (entry or "")
        if date >= cutoff:
            kept[key] = entry
    if before - len(kept):
        print(f"[State] {before - len(kept)} tracks vergeten (ouder dan {SEEN_EXPIRY_DAYS}d)")
    return kept


def main():
    print(f"\n{'='*50}")
    print(f"  Ochtendjazz update — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    state        = load_state()
    seen         = prune_seen(state["seen"])
    playlist_log = state["playlist_log"]

    session = load_tidal_session()
    print("[Tidal] Ingelogd ✓\n")

    playlist_log = remove_old_tracks(session, TIDAL_PLAYLIST_ID, playlist_log)

    network = get_lastfm_network()
    try:
        token = get_spotify_token()
        print("[Spotify] Token verkregen ✓ (alleen voor genrecontrole)\n")
    except Exception as e:
        print(f"[Spotify] Token mislukt: {e}\n")
        token = None

    candidates = (get_tag_radio(network)
                  + get_seed_tracks(network)
                  + get_similar_discoveries(network))

    # Dubbels eruit, blokkeerlijst toepassen
    unique = {}
    for c in candidates:
        c["title"] = clean_title(c["title"])
        if c["artist"].strip().lower() in BLOCKED_ARTISTS:
            continue
        unique.setdefault(normalize_key(c["artist"], c["title"]), c)
    candidates = list(unique.values())
    print(f"\nKandidaten na ontdubbelen: {len(candidates)}")

    # Genrecontrole per artiest, één keer opzoeken en onthouden
    if token:
        genre_cache = {}
        kept = []
        for c in candidates:
            name = c["artist"]
            if name not in genre_cache:
                genre_cache[name] = lookup_genres_by_name(token, name)
            c["genres"] = genre_cache[name][:4]
            verdict = genre_verdict(genre_cache[name])
            if verdict == "blocked" and name.strip().lower() not in ALLOWED_ARTISTS:
                continue
            kept.append(c)
        print(f"Kandidaten na genrecontrole: {len(kept)}")
        candidates = kept

    random.shuffle(candidates)

    existing_tidal_ids = get_existing_tidal_ids(session, TIDAL_PLAYLIST_ID)
    print(f"Huidig in playlist: {len(existing_tidal_ids)}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    added = []

    for candidate in candidates:
        if len(added) >= TARGET_ADDITIONS:
            break

        artist = candidate["artist"]
        title  = candidate["title"]
        source = candidate["source"]
        key    = normalize_key(artist, title)

        if key in seen:
            continue

        # Tempotoets op tags: negatief betekent snel, luid of atonaal
        score = tag_score(network, artist, title)
        if score < 0:
            print(f"  ✗ [{source}] {artist} — {title} (te snel volgens tags)")
            seen[key] = {"date": today, "source": source}
            continue

        tidal_track = search_tidal_track(session, artist, title)
        if not tidal_track:
            print(f"  ✗ [{source}] {artist} — {title} (niet gevonden op Tidal)")
            continue

        duration = getattr(tidal_track, "duration", 0) or 0
        if duration and not (MIN_DURATION <= duration <= MAX_DURATION):
            print(f"  ✗ [{source}] {artist} — {title} ({duration}s, buiten bereik)")
            seen[key] = {"date": today, "source": source}
            continue

        tidal_id = str(tidal_track.id)
        if tidal_id in existing_tidal_ids:
            seen[key] = {"date": today, "source": source}
            continue

        added.append(tidal_track)
        existing_tidal_ids.add(tidal_id)
        seen[key]              = {"date": today, "source": source}
        playlist_log[tidal_id] = {"date": today, "artist": artist, "title": title,
                                  "source": source, "genres": candidate.get("genres", [])}
        print(f"  ✓ [{source}] {artist} — {title} (tagscore {score})")

    if added:
        session.playlist(TIDAL_PLAYLIST_ID).add([t.id for t in added])
        print(f"\n[Tidal] {len(added)} tracks toegevoegd ✓")
    else:
        print("\n[Tidal] Geen nieuwe tracks gevonden.")

    state["seen"]         = seen
    state["playlist_log"] = playlist_log
    save_state(state)
    print(f"\nKlaar! {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
