"""
Eenmalige cleanup: verwijdert tracks uit de Tidal playlist waarvan
de artiest een geblokkeerd genre heeft op Spotify.
Werkt op de huidige playlist-inhoud, ongeacht state.json.
"""
import os, json, requests, tidalapi, pylast
from pathlib import Path

TIDAL_PLAYLIST_ID     = os.environ["TIDAL_PLAYLIST_ID"]
SPOTIFY_CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
LASTFM_PASSWORD_HASH  = pylast.md5(os.environ["LASTFM_PASSWORD"])

BLOCKED_GENRES = {
    "rap", "hip hop", "trap", "drill", "grime",
    "hard rock", "heavy metal", "metal", "punk",
    "hardcore", "noise rock", "death metal", "thrash metal",
    "edm", "electro house", "big room",
}

STATE_FILE = Path("state.json")

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {"seen": {}, "playlist_log": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def get_spotify_token():
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET), timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def search_spotify_artist_id(token, artist_name):
    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": artist_name, "type": "artist", "limit": 1},
        timeout=10,
    )
    items = r.json().get("artists", {}).get("items", [])
    return items[0]["id"] if items else None

def get_genres_for_artist_id(token, artist_id):
    r = requests.get(
        f"https://api.spotify.com/v1/artists/{artist_id}",
        headers={"Authorization": f"Bearer {token}"}, timeout=10,
    )
    return r.json().get("genres", [])

def is_blocked(genres):
    return any(blocked in genre for genre in genres for blocked in BLOCKED_GENRES)

def main():
    print("\n" + "="*50)
    print("  Genre-cleanup van bestaande playlist")
    print("="*50 + "\n")

    session = tidalapi.Session()
    session.load_session_from_file(Path("/tmp/tidal_session.json"))
    print("[Tidal] Ingelogd ✓")

    token = get_spotify_token()
    print("[Spotify] Token verkregen ✓\n")

    tracks = list(session.playlist(TIDAL_PLAYLIST_ID).tracks())
    print(f"{len(tracks)} tracks in playlist\n")

    state = load_state()
    playlist_log = state.get("playlist_log", {})

    genre_cache = {}
    indices_to_remove = []

    for idx, track in enumerate(tracks):
        artist_name = track.artist.name
        tidal_id    = str(track.id)

        if artist_name not in genre_cache:
            artist_id = search_spotify_artist_id(token, artist_name)
            if artist_id:
                genres = get_genres_for_artist_id(token, artist_id)
            else:
                genres = []
            genre_cache[artist_name] = genres

        genres = genre_cache[artist_name]

        if is_blocked(genres):
            blocked_matches = [g for g in genres if any(b in g for b in BLOCKED_GENRES)]
            print(f"  ✗ [{idx}] {artist_name} — {track.name}  →  {blocked_matches}")
            indices_to_remove.append((idx, tidal_id))
        else:
            print(f"  ✓ [{idx}] {artist_name} — {track.name}")

    if not indices_to_remove:
        print("\nGeen verboden genres gevonden. Playlist is al clean.")
        return

    print(f"\n{len(indices_to_remove)} tracks verwijderen…")
    pl = session.playlist(TIDAL_PLAYLIST_ID)
    for idx, tidal_id in sorted(indices_to_remove, reverse=True):
        pl.remove_by_index(idx)
        playlist_log.pop(tidal_id, None)

    state["playlist_log"] = playlist_log
    save_state(state)
    print(f"\n✓ {len(indices_to_remove)} tracks verwijderd en uit state.json gehaald")
    print(f"Klaar!\n")

if __name__ == "__main__":
    main()
