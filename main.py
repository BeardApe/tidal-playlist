"""
Dagelijkse Tidal Playlist Builder
Combineert Radio 1 (Duyster), Studio Brussel (Vuurland) en Last.fm discoveries
met een nostalgische indie/trip-hop vibe.
"""

import os
import json
import random
import requests
import tidalapi
import pylast
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# CONFIGURATIE
# ─────────────────────────────────────────────

TIDAL_PLAYLIST_ID = os.environ["TIDAL_PLAYLIST_ID"]   # ID van je bestaande playlist
LASTFM_API_KEY    = os.environ["LASTFM_API_KEY"]
LASTFM_API_SECRET = os.environ["LASTFM_API_SECRET"]
LASTFM_USERNAME   = os.environ["LASTFM_USERNAME"]
LASTFM_PASSWORD_HASH = pylast.md5(os.environ["LASTFM_PASSWORD"])

# Hoeveel tracks per dag toevoegen
TRACKS_PER_DAY     = 12   # ~2 uur muziek
MAX_PLAYLIST_SIZE  = 300  # playlist cap — oudste tracks vallen eraf

# Seed-artiesten voor de vibe
SEED_ARTISTS = [
    "Zero 7", "Moloko", "Air", "Beach House", "SOHN",
    "Portishead", "Massive Attack", "Bonobo", "Röyksopp",
    "Thievery Corporation", "The XX", "London Grammar",
    "Daughter", "Sigur Rós", "Boards of Canada",
    "Nick Drake", "Feist", "Jose Gonzalez",
    "Four Tet", "Moderat", "Nils Frahm",
    "Agnes Obel", "Soap&Skin", "Warpaint",
    "Cigarettes After Sex", "Still Woozy", "Novo Amor",
]


# ─────────────────────────────────────────────
# TIDAL SESSIE
# ─────────────────────────────────────────────

def load_tidal_session() -> tidalapi.Session:
    """Laad Tidal sessie vanuit JSON bestand (aangemaakt door workflow)."""
    from pathlib import Path
    session = tidalapi.Session()
    session_file = Path("/tmp/tidal_session.json")
    session.load_session_from_file(session_file)

    if not session.check_login():
        raise RuntimeError("Tidal sessie verlopen — voer setup.py opnieuw uit.")

    return session


# ─────────────────────────────────────────────
# RADIO 1 DUYSTER — recente tracklist
# ─────────────────────────────────────────────

def get_radio1_tracks() -> list[dict]:
    """
    Haal de meest recente Duyster-tracks op via de VRT tracklist API.
    Duyster: ma-vr 22:00-24:00 op Radio 1
    """
    tracks = []

    try:
        # VRT publieke tracklist API
        url = "https://www.radio1.be/api/tracks"
        params = {"channel": "radio1", "limit": 50}
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PlaylistBot/1.0)"}

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # De API geeft een lijst van recente tracks terug
        items = data.get("items", data) if isinstance(data, dict) else data

        for item in items[:30]:
            artist = item.get("artist") or item.get("artistName", "")
            title  = item.get("title")  or item.get("trackTitle", "")
            if artist and title:
                tracks.append({"artist": artist.strip(), "title": title.strip(), "source": "Radio1-Duyster"})

    except Exception as e:
        print(f"[Radio 1] Scrape mislukt: {e}")

    print(f"[Radio 1] {len(tracks)} tracks gevonden")
    return tracks


# ─────────────────────────────────────────────
# STUDIO BRUSSEL VUURLAND — recente tracklist
# ─────────────────────────────────────────────

def get_stubru_tracks() -> list[dict]:
    """
    Haal de meest recente Vuurland-tracks op via de Studio Brussel website.
    Vuurland: do-vr 22:00-24:00 op Studio Brussel
    """
    tracks = []

    try:
        url = "https://www.stubru.be/api/tracks"
        params = {"channel": "stubru", "limit": 50}
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PlaylistBot/1.0)"}

        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", data) if isinstance(data, dict) else data

        for item in items[:30]:
            artist = item.get("artist") or item.get("artistName", "")
            title  = item.get("title")  or item.get("trackTitle", "")
            if artist and title:
                tracks.append({"artist": artist.strip(), "title": title.strip(), "source": "StubRu-Vuurland"})

    except Exception as e:
        print(f"[Studio Brussel] Scrape mislukt: {e}")

    print(f"[Studio Brussel] {len(tracks)} tracks gevonden")
    return tracks


# ─────────────────────────────────────────────
# LAST.FM — soortgelijke artiesten & nieuwe tracks
# ─────────────────────────────────────────────

def get_lastfm_discoveries(n_artists: int = 5, tracks_per_artist: int = 3) -> list[dict]:
    """
    Kies willekeurig N seed-artiesten → zoek soortgelijke artiesten via Last.fm
    → haal hun populairste tracks op als ontdekkingen.
    """
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
            artist = network.get_artist(seed_name)
            similar = artist.get_similar(limit=8)

            # Kies willekeurig 2 soortgelijke artiesten
            picks = random.sample(similar, min(2, len(similar)))

            for similar_item in picks:
                sim_artist = similar_item.item
                top_tracks = sim_artist.get_top_tracks(limit=10)

                # Kies willekeurig tracks
                selected = random.sample(top_tracks, min(tracks_per_artist, len(top_tracks)))

                for tt in selected:
                    tracks.append({
                        "artist": str(sim_artist.name),
                        "title":  str(tt.item.title),
                        "source": f"LastFM-similar-to-{seed_name}",
                    })

        except Exception as e:
            print(f"[Last.fm] Fout bij {seed_name}: {e}")

    print(f"[Last.fm] {len(tracks)} ontdekkingen")
    return tracks


# ─────────────────────────────────────────────
# TIDAL — zoek track & voeg toe aan playlist
# ─────────────────────────────────────────────

def search_tidal_track(session: tidalapi.Session, artist: str, title: str):
    """Zoek een track op Tidal. Geeft een Track-object terug of None."""
    query = f"{artist} {title}"
    try:
        results = session.search(query, models=[tidalapi.media.Track], limit=5)
        tracks = results.get("tracks", [])

        for track in tracks:
            # Controleer of artiest grofweg overeenkomt
            track_artist = track.artist.name.lower()
            if artist.lower() in track_artist or track_artist in artist.lower():
                return track

        # Fallback: eerste resultaat
        return tracks[0] if tracks else None

    except Exception as e:
        print(f"  [Tidal] Zoekfout '{query}': {e}")
        return None


def get_existing_track_ids(session: tidalapi.Session, playlist_id: str) -> set:
    """Haal alle track-IDs op die al in de playlist zitten."""
    try:
        playlist = session.playlist(playlist_id)
        tracks = list(playlist.tracks())
        return {t.id for t in tracks}
    except Exception as e:
        print(f"[Tidal] Kon bestaande tracks niet ophalen: {e}")
        return set()


def trim_playlist_if_needed(session: tidalapi.Session, playlist_id: str, max_size: int):
    """Verwijder de oudste tracks als de playlist te groot wordt."""
    try:
        playlist = session.playlist(playlist_id)
        tracks = list(playlist.tracks())

        if len(tracks) <= max_size:
            return

        to_remove = len(tracks) - max_size
        indices_to_remove = list(range(to_remove))  # oudste tracks vooraan
        playlist.remove_by_indices(indices_to_remove)
        print(f"[Tidal] {to_remove} oude tracks verwijderd (cap: {max_size})")

    except Exception as e:
        print(f"[Tidal] Trim mislukt: {e}")


# ─────────────────────────────────────────────
# HOOFD-LOGICA
# ─────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print(f"  Playlist update — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    # 1. Laad Tidal sessie
    session = load_tidal_session()
    print("[Tidal] Ingelogd ✓")

    # 2. Verzamel kandidaat-tracks uit alle bronnen
    candidates = []
    candidates += get_radio1_tracks()
    candidates += get_stubru_tracks()
    candidates += get_lastfm_discoveries()

    # Schud en beperk
    random.shuffle(candidates)
    print(f"\nTotaal kandidaten: {len(candidates)}")

    # 3. Haal bestaande track-IDs op (geen duplicaten)
    existing_ids = get_existing_track_ids(session, TIDAL_PLAYLIST_ID)
    print(f"Bestaande tracks in playlist: {len(existing_ids)}")

    # 4. Zoek elke kandidaat op Tidal en voeg toe
    added = []

    for candidate in candidates:
        if len(added) >= TRACKS_PER_DAY:
            break

        artist = candidate["artist"]
        title  = candidate["title"]
        source = candidate["source"]

        tidal_track = search_tidal_track(session, artist, title)

        if tidal_track and tidal_track.id not in existing_ids:
            added.append(tidal_track)
            existing_ids.add(tidal_track.id)
            print(f"  ✓ [{source}] {artist} — {title}")
        else:
            reason = "al aanwezig" if tidal_track and tidal_track.id in existing_ids else "niet gevonden"
            print(f"  ✗ [{source}] {artist} — {title} ({reason})")

    # 5. Voeg toe aan Tidal playlist
    if added:
        playlist = session.playlist(TIDAL_PLAYLIST_ID)
        playlist.add([t.id for t in added])
        print(f"\n[Tidal] {len(added)} tracks toegevoegd ✓")
    else:
        print("\n[Tidal] Geen nieuwe tracks gevonden vandaag.")

    # 6. Trim als nodig
    trim_playlist_if_needed(session, TIDAL_PLAYLIST_ID, MAX_PLAYLIST_SIZE)

    print(f"\nKlaar! {datetime.now().strftime('%H:%M:%S')}\n")


if __name__ == "__main__":
    main()
