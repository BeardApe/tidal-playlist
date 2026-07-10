"""
Dagelijkse Tidal Playlist Builder
State (state.json in repo):
  - seen:         {normalized_key: {date, source}} 
  - playlist_log: {tidal_id: {date, artist, title, source}}
"""

import os
import json
import random
import requests
import tidalapi
import pylast
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIDAL_PLAYLIST_ID     = os.environ["TIDAL_PLAYLIST_ID"]
LASTFM_API_KEY        = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET     = os.environ["LASTFM_API_SECRET"]
LASTFM_USERNAME       = os.environ["LASTFM_USERNAME"]
LASTFM_PASSWORD_HASH  = pylast.md5(os.environ["LASTFM_PASSWORD"])
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]

MAX_AGE_DAYS   = 30
NEW_TRACK_DAYS = 21

STATE_FILE = Path("state.json")

BLOCKED_GENRES = {
    "rap", "hip hop", "trap", "drill", "grime",
    "hard rock", "heavy metal", "metal", "punk",
    "hardcore", "noise rock", "death metal", "thrash metal",
    "edm", "electro house", "big room",
}

RECENCY_FILTER_PLAYLISTS = {"Nummers-2026"}

SPOTIFY_PLAYLISTS = [
    ("2PKUCBZT1plQsR0I7mQRIR", "Vuurland-latest"),
    ("57ZB4USGsQpJXS4CV19v1l", "Radio1-Top30"),
    ("2ZjYdntfOlz3SQFhqGXJJb", "Radio1-Wonderland"),
    ("3BR9yVqXbaFZeSE87kvtoJ", "Nummers-2026"),
    ("7ro9wf8vuSLGxStaC8t8Rv", "NPR-AllSongsConsidered"),
    ("3iDApphZb5wI9w9ZFsftmO", "GuyGarvey-FinestHour"),
    ("1CnggIDx6I8wgHOnaTiyLI", "LateJunction-Official"),
    ("3hFEXeWLaMQdBvdd32KwXR", "LaurenLaverne-JustAdded"),
    ("60VayqPuLXaftoj2Wrqpti", "KEXP-NewThisWeek"),
    ("4t9mOf6WlfO8oK1PcVzPRM", "WFUV-NYSlice2026"),
]

SEED_ARTISTS = [
    "Zero 7", "Moloko", "Air", "Beach House", "SOHN",
    "Portishead", "Massive Attack", "Bonobo", "Röyksopp",
    "Thievery Corporation", "The XX", "London Grammar",
    "Daughter", "Sigur Rós", "Boards of Canada",
    "Nick Drake", "Feist", "Jose Gonzalez",
    "Four Tet", "Moderat", "Nils Frahm",
    "Agnes Obel", "Warpaint", "Cigarettes After Sex",
    "Still Woozy", "Novo Amor", "Aldous Harding",
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


def load_tidal_session() -> tidalapi.Session:
    session = tidalapi.Session()
    session.load_session_from_file(Path("/tmp/tidal_session.json"))
    return session


def get_spotify_token() -> str:
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_artist_genres(token: str, artist_ids: list[str]) -> dict[str, list[str]]:
    genres = {}
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(0, len(artist_ids), 50):
        batch = artist_ids[i:i+50]
        resp = requests.get(
            "https://api.spotify.com/v1/artists",
            headers=headers,
            params={"ids": ",".join(batch)},
            timeout=10,
        )
        if resp.status_code == 200:
            for artist in resp.json().get("artists", []) or []:
                if artist:
                    genres[artist["id"]] = artist.get("genres", [])
    return genres


def is_blocked(artist_id: str, genre_map: dict) -> bool:
    return any(
        blocked in genre
        for genre in genre_map.get(artist_id, [])
        for blocked in BLOCKED_GENRES
    )


def get_spotify_playlist_tracks(
    token: str, playlist_id: str, source_name: str, only_recent: bool = False,
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEW_TRACK_DAYS)
    tracks = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"limit": 100, "fields": "items(added_at,track(name,artists(name,id))),next"}

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"  [Spotify] Fout {resp.status_code} voor {source_name}")
            break
        data = resp.json()
        for item in data.get("items", []):
            track = item.get("track")
            if not track or not track.get("name") or not track.get("artists"):
                continue
            if only_recent:
                try:
                    added_at = datetime.fromisoformat(item.get("added_at", "").replace("Z", "+00:00"))
                    if added_at < cutoff:
                        continue
                except (ValueError, AttributeError):
                    continue
            tracks.append({
                "artist":    track["artists"][0]["name"],
                "artist_id": track["artists"][0].get("id", ""),
                "title":     track["name"],
                "source":    source_name,
            })
        url = data.get("next")
        params = {}

    return tracks


def get_all_spotify_tracks(token: str) -> list[dict]:
    all_tracks = []
    for playlist_id, source_name in SPOTIFY_PLAYLISTS:
        only_recent = source_name in RECENCY_FILTER_PLAYLISTS
        try:
            tracks = get_spotify_playlist_tracks(token, playlist_id, source_name, only_recent)
            sample = random.sample(tracks, min(20, len(tracks)))
            all_tracks.extend(sample)
            label = f" (laatste {NEW_TRACK_DAYS}d)" if only_recent else ""
            print(f"[Spotify] {source_name}{label}: {len(sample)} gekozen uit {len(tracks)}")
        except Exception as e:
            print(f"[Spotify] Fout bij {source_name}: {e}")
    return all_tracks


def get_lastfm_discoveries(n_artists: int = 4, tracks_per_artist: int = 3) -> list[dict]:
    network = pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY, api_secret=LASTFM_API_SECRET,
        username=LASTFM_USERNAME, password_hash=LASTFM_PASSWORD_HASH,
    )
    tracks = []
    for seed_name in random.sample(SEED_ARTISTS, min(n_artists, len(SEED_ARTISTS))):
        try:
            similar = network.get_artist(seed_name).get_similar(limit=8)
            for similar_item in random.sample(similar, min(2, len(similar))):
                sim_artist = similar_item.item
                top_tracks = sim_artist.get_top_tracks(limit=10)
                for tt in random.sample(top_tracks, min(tracks_per_artist, len(top_tracks))):
                    tracks.append({
                        "artist": str(sim_artist.name), "artist_id": "",
                        "title": str(tt.item.title), "source": f"LastFM~{seed_name}",
                    })
        except Exception as e:
            print(f"[Last.fm] Fout bij {seed_name}: {e}")
    print(f"[Last.fm] {len(tracks)} ontdekkingen")
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
            if isinstance(e, dict): return e.get("date", "9999-12-31")
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


def backfill_playlist_log(session: tidalapi.Session, playlist_id: str, playlist_log: dict) -> dict:
    """
    Vult ontbrekende artiest/titel aan voor oude entries (van vóór het rijke formaat).
    Leest de gegevens rechtstreeks uit de Tidal playlist.
    """
    try:
        enriched = 0
        for track in session.playlist(playlist_id).tracks():
            tid   = str(track.id)
            entry = playlist_log.get(tid)
            if entry is None:
                continue
            if isinstance(entry, str):
                entry = {"date": entry}
            if not entry.get("artist") or not entry.get("title"):
                entry["artist"] = entry.get("artist") or track.artist.name
                entry["title"]  = entry.get("title")  or track.name
                entry.setdefault("source", "onbekend")
                enriched += 1
            playlist_log[tid] = entry
        if enriched:
            print(f"[Backfill] {enriched} oude entries aangevuld met artiest/titel")
    except Exception as e:
        print(f"[Backfill] Mislukt: {e}")
    return playlist_log


def main():
    print(f"\n{'='*50}")
    print(f"  Playlist update — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    state        = load_state()
    seen         = state["seen"]
    playlist_log = state["playlist_log"]

    session = load_tidal_session()
    print("[Tidal] Ingelogd ✓\n")

    playlist_log = remove_old_tracks(session, TIDAL_PLAYLIST_ID, playlist_log)
    playlist_log = backfill_playlist_log(session, TIDAL_PLAYLIST_ID, playlist_log)

    try:
        token = get_spotify_token()
        print("[Spotify] Token verkregen ✓")
    except Exception as e:
        print(f"[Spotify] Token mislukt: {e}")
        token = None

    spotify_candidates = get_all_spotify_tracks(token) if token else []
    lastfm_candidates  = get_lastfm_discoveries()

    # Genre-filter op Spotify-kandidaten
    genre_map = {}
    if token and spotify_candidates:
        artist_ids = list({c["artist_id"] for c in spotify_candidates if c.get("artist_id")})
        genre_map  = fetch_artist_genres(token, artist_ids)
        before     = len(spotify_candidates)
        spotify_candidates = [c for c in spotify_candidates if not is_blocked(c.get("artist_id", ""), genre_map)]
        blocked_n  = before - len(spotify_candidates)
        if blocked_n:
            print(f"[Genre] {blocked_n} tracks geblokkeerd op genre")

    candidates = spotify_candidates + lastfm_candidates
    random.shuffle(candidates)
    print(f"\nTotaal kandidaten na filtering: {len(candidates)}")

    existing_tidal_ids = get_existing_tidal_ids(session, TIDAL_PLAYLIST_ID)
    print(f"Huidig in playlist: {len(existing_tidal_ids)}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    added = []

    for candidate in candidates:
        artist = candidate["artist"]
        title  = candidate["title"]
        source = candidate["source"]
        key    = normalize_key(artist, title)

        seen_entry = seen.get(key)
        if seen_entry:
            if isinstance(seen_entry, str):
                # Heel oude entries: bewaar oorspronkelijke datum, vul bron aan
                seen[key] = {"date": seen_entry, "source": source}
                date_seen = seen_entry
            else:
                if seen_entry.get("source") in (None, "", "onbekend"):
                    seen_entry["source"] = source
                date_seen = seen_entry.get("date", "")
            print(f"  – [{source}] {artist} — {title} (al toegevoegd op {date_seen})")
            continue

        tidal_track = search_tidal_track(session, artist, title)
        if not tidal_track:
            print(f"  ✗ [{source}] {artist} — {title} (niet gevonden op Tidal)")
            continue

        tidal_id = str(tidal_track.id)
        if tidal_id in existing_tidal_ids:
            print(f"  – [{source}] {artist} — {title} (staat al in playlist)")
            seen[key] = {"date": today, "source": source}
            # Heel oude entries: vul ontbrekende bron en genres aan
            log_entry = playlist_log.get(tidal_id)
            if isinstance(log_entry, dict):
                if log_entry.get("source") in (None, "", "onbekend"):
                    log_entry["source"] = source
                if not log_entry.get("genres"):
                    log_entry["genres"] = genre_map.get(candidate.get("artist_id", ""), [])[:4]
            continue

        added.append(tidal_track)
        existing_tidal_ids.add(tidal_id)
        genres = genre_map.get(candidate.get("artist_id", ""), [])[:4]
        seen[key]              = {"date": today, "source": source}
        playlist_log[tidal_id] = {"date": today, "artist": artist, "title": title,
                                  "source": source, "genres": genres}
        print(f"  ✓ [{source}] {artist} — {title}")

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
