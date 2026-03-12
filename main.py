"""
Dagelijkse Tidal Playlist Builder
Bronnen:
  - Spotify: Vuurland (latest), Radio 1 Top 30, Radio 1 Wonderland, Nummers 2026 (alleen nieuw),
             NPR All Songs Considered, Guy Garvey's Finest Hour, Late Junction,
             Lauren Laverne Just Added, KEXP New This Week, WFUV NY Slice 2026
  - Last.fm: similar artists gebaseerd op seed-artiesten

State (state.json in repo):
  - seen:         {normalized_key: datum} — tracks die ooit al zijn toegevoegd
  - playlist_log: {tidal_id: datum}       — wanneer elke track in de playlist is gezet
"""

import os
import json
import random
import requests
import tidalapi
import pylast
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATIE
# ─────────────────────────────────────────────

TIDAL_PLAYLIST_ID     = os.environ["TIDAL_PLAYLIST_ID"]
LASTFM_API_KEY        = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET     = os.environ["LASTFM_API_SECRET"]
LASTFM_USERNAME       = os.environ["LASTFM_USERNAME"]
LASTFM_PASSWORD_HASH  = pylast.md5(os.environ["LASTFM_PASSWORD"])
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]

MAX_AGE_DAYS   = 30   # tracks ouder dan dit worden uit de Tidal playlist verwijderd
NEW_TRACK_DAYS = 21   # Nummers-2026: alleen tracks toegevoegd in de afgelopen N dagen

STATE_FILE = Path("state.json")

# Playlists waarbij we alleen RECENT TOEGEVOEGDE tracks pakken
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


# ─────────────────────────────────────────────
# STATE BEHEER
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# TIDAL SESSIE
# ─────────────────────────────────────────────

def load_tidal_session() -> tidalapi.Session:
    session = tidalapi.Session()
    session.load_session_from_file(Path("/tmp/tidal_session.json"))
    return session


# ─────────────────────────────────────────────
# SPOTIFY — tracks ophalen uit playlists
# ─────────────────────────────────────────────

def get_spotify_token() -> str:
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_spotify_playlist_tracks(
    token: str,
    playlist_id: str,
    source_name: str,
    only_recent: bool = False,
) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEW_TRACK_DAYS)
    tracks = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "limit": 100,
        "fields": "items(added_at,track(name,artists(name))),next",
    }

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
                added_at_str = item.get("added_at", "")
                try:
                    added_at = datetime.fromisoformat(added_at_str.replace("Z", "+00:00"))
                    if added_at < cutoff:
                        continue
                except (ValueError, AttributeError):
                    continue
            tracks.append({
                "artist": track["artists"][0]["name"],
                "title":  track["name"],
                "source": source_name,
            })
        url = data.get("next")
        params = {}

    return tracks


def get_all_spotify_tracks() -> list[dict]:
    try:
        token = get_spotify_token()
        print("[Spotify] Token verkregen ✓")
    except Exception as e:
        print(f"[Spotify] Token mislukt: {e}")
        return []

    all_tracks = []
    for playlist_id, source_name in SPOTIFY_PLAYLISTS:
        only_recent = source_name in RECENCY_FILTER_PLAYLISTS
        try:
            tracks = get_spotify_playlist_tracks(token, playlist_id, source_name, only_recent)
            sample = random.sample(tracks, min(20, len(tracks)))
            all_tracks.extend(sample)
            filter_label = f" (laatste {NEW_TRACK_DAYS}d)" if only_recent else ""
            print(f"[Spotify] {source_name}{filter_label}: {len(sample)} gekozen uit {len(tracks)}")
        except Exception as e:
            print(f"[Spotify] Fout bij {source_name}: {e}")

    return all_tracks


# ─────────────────────────────────────────────
# LAST.FM — similar artists
# ─────────────────────────────────────────────

def get_lastfm_discoveries(n_artists: int = 4, tracks_per_artist: int = 3) -> list[dict]:
    network = pylast.LastFMNetwork(
        api_key=LASTFM_API_KEY,
        api_secret=LASTFM_API_SECRET,
        username=LASTFM_USERNAME,
        password_hash=LASTFM_PASSWORD_HASH,
    )

    tracks = []
    chosen_seeds = random.sample(SEED_ARTISTS, min(n_artists, len(SEED_ARTISTS)))

    for seed_name in chosen_seeds:
        try:
            artist  = network.get_artist(seed_name)
            similar = artist.get_similar(limit=8)
            picks   = random.sample(similar, min(2, len(similar)))

            for similar_item in picks:
                sim_artist = similar_item.item
                top_tracks = sim_artist.get_top_tracks(limit=10)
                selected   = random.sample(top_tracks, min(tracks_per_artist, len(top_tracks)))
                for tt in selected:
                    tracks.append({
                        "artist": str(sim_artist.name),
                        "title":  str(tt.item.title),
                        "source": f"LastFM~{seed_name}",
                    })
        except Exception as e:
            print(f"[Last.fm] Fout bij {seed_name}: {e}")

    print(f"[Last.fm] {len(tracks)} ontdekkingen")
    return tracks


# ─────────────────────────────────────────────
# TIDAL — zoeken & playlist beheer
# ─────────────────────────────────────────────

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
        tracks = list(session.playlist(playlist_id).tracks())
        tidal_ids = [str(t.id) for t in tracks]

        indices_to_remove = [
            idx for idx, tid in enumerate(tidal_ids)
            if playlist_log.get(tid, "9999-12-31") < cutoff
        ]

        if indices_to_remove:
            for idx in sorted(indices_to_remove, reverse=True):
                session.playlist(playlist_id).remove_by_index(idx)
            for idx in indices_to_remove:
                playlist_log.pop(tidal_ids[idx], None)
            print(f"[Tidal] {len(indices_to_remove)} tracks ouder dan {MAX_AGE_DAYS} dagen verwijderd")
        else:
            print(f"[Tidal] Geen tracks ouder dan {MAX_AGE_DAYS} dagen")

    except Exception as e:
        print(f"[Tidal] Rotatie mislukt: {e}")

    return playlist_log


# ─────────────────────────────────────────────
# HOOFD-LOGICA
# ─────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Playlist update — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    state        = load_state()
    seen         = state["seen"]
    playlist_log = state["playlist_log"]

    session = load_tidal_session()
    print("[Tidal] Ingelogd ✓\n")

    # Stap 1: verwijder tracks ouder dan MAX_AGE_DAYS
    playlist_log = remove_old_tracks(session, TIDAL_PLAYLIST_ID, playlist_log)

    # Stap 2: verzamel kandidaten
    spotify_candidates = get_all_spotify_tracks()
    lastfm_candidates  = get_lastfm_discoveries()
    candidates = spotify_candidates + lastfm_candidates
    random.shuffle(candidates)
    print(f"\nTotaal kandidaten: {len(candidates)}")

    existing_tidal_ids = get_existing_tidal_ids(session, TIDAL_PLAYLIST_ID)
    print(f"Huidig aantal tracks in playlist: {len(existing_tidal_ids)}\n")

    today = datetime.now().strftime("%Y-%m-%d")
    added = []

    for candidate in candidates:
        artist = candidate["artist"]
        title  = candidate["title"]
        source = candidate["source"]
        key    = normalize_key(artist, title)

        if key in seen:
            print(f"  – [{source}] {artist} — {title} (al eerder toegevoegd op {seen[key]})")
            continue

        tidal_track = search_tidal_track(session, artist, title)

        if not tidal_track:
            print(f"  ✗ [{source}] {artist} — {title} (niet gevonden op Tidal)")
            continue

        tidal_id = str(tidal_track.id)

        if tidal_id in existing_tidal_ids:
            print(f"  – [{source}] {artist} — {title} (staat al in playlist)")
            seen[key] = today
            continue

        added.append(tidal_track)
        existing_tidal_ids.add(tidal_id)
        seen[key]              = today
        playlist_log[tidal_id] = today
        print(f"  ✓ [{source}] {artist} — {title}")

    if added:
        session.playlist(TIDAL_PLAYLIST_ID).add([t.id for t in added])
        print(f"\n[Tidal] {len(added)} tracks toegevoegd ✓")
    else:
        print("\n[Tidal] Geen nieuwe tracks gevonden vandaag.")

    state["seen"]         = seen
    state["playlist_log"] = playlist_log
    save_state(state)

    print(f"\nKlaar! {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
