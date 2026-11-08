"""
Rustniveau per nummer en de rustige afgeleiden van Nachtradio.

Elk nummer in playlist_log krijgt "rust": 1 (zacht, traag, akoestisch) tot 5 (stevig).
Bron: audio-features van ReccoBeats (gratis, zonder sleutel), opgezocht op ISRC.
Vindt ReccoBeats het nummer niet, dan een schatting uit bron en genres ("rust_bron": "schatting").

Daarna worden twee Tidal-playlists gelijkgezet met Nachtradio:
  Nachtradio Avond: rust 1 tot 3 (Home Assistant vanaf 20u)
  Nachtradio Nacht: rust 1 tot 2 (Home Assistant vanaf 22u)
Ze hebben geen eigen boekhouding: wat uit Nachtradio gaat (rotatie, blokkade) gaat er ook uit.
"""
import time
import requests

RECCO_URL = "https://api.reccobeats.com/v1/audio-features"
RECCO_BATCH = 40

RUST_PLAYLISTS = {
    "avond": ("Nachtradio Avond", 3, "Rustige nummers uit Nachtradio, voor de avond. Automatisch bijgehouden."),
    "nacht": ("Nachtradio Nacht", 2, "De zachtste nummers uit Nachtradio, voor laat op de avond. Automatisch bijgehouden."),
}

# Grenzen op de intensiteit (0 tot 1): onder 0,30 is niveau 1, onder 0,45 niveau 2, enzovoort
GRENZEN = [0.30, 0.45, 0.60, 0.75]

RUSTIGE_BRONNEN = {"Duyster", "SomaFM-Lush", "RadioParadise-Mellow"}
RUSTIGE_GENRES = ("ambient", "folk", "singer songwriter", "singer-songwriter", "acoustic", "chamber",
                  "slowcore", "sadcore", "piano", "neoclassical", "neo classical", "lullaby", "bossa",
                  "vocal jazz", "chillout", "chill", "mellow", "dream pop", "downtempo", "trip hop")
STEVIGE_GENRES = ("rock", "punk", "dance", "house", "disco", "funk", "electro", "garage", "techno",
                  "hip hop", "rap", "metal", "drum and bass", "big beat", "pop punk")


def _klem(x: float) -> float:
    return max(0.0, min(1.0, x))


def intensiteit(f: dict) -> float:
    """Eén getal van 0 (heel rustig) tot 1 (heel stevig) uit de audio-features."""
    luid = _klem((f.get("loudness", -12) + 25) / 20)     # -25 dB = 0, -5 dB = 1
    tempo = _klem((f.get("tempo", 110) - 70) / 80)        # 70 bpm = 0, 150 bpm = 1
    return round(0.55 * f.get("energy", 0.5) + 0.20 * luid
                 + 0.15 * (1 - f.get("acousticness", 0.5)) + 0.10 * tempo, 3)


def niveau(i: float) -> int:
    return 1 + sum(i >= g for g in GRENZEN)


def schatting(entry: dict) -> int:
    genres = " ".join(entry.get("genres") or []).lower().replace("-", " ")
    rustig = any(g.replace("-", " ") in genres for g in RUSTIGE_GENRES)
    stevig = any(g in genres for g in STEVIGE_GENRES)
    if entry.get("source") in RUSTIGE_BRONNEN:
        return 3 if stevig else 2
    if rustig and not stevig:
        return 3
    return 4


def _recco(isrcs: list[str]) -> dict[str, dict]:
    """Audio-features per ISRC. Meerdere versies van hetzelfde ISRC: de eerste telt."""
    uit = {}
    for i in range(0, len(isrcs), RECCO_BATCH):
        deel = isrcs[i:i + RECCO_BATCH]
        for poging in range(3):
            try:
                r = requests.get(RECCO_URL, params={"ids": ",".join(deel)}, timeout=30)
                if r.status_code == 429:
                    time.sleep(int(r.headers.get("Retry-After", 5)) + 1)
                    continue
                r.raise_for_status()
                for f in r.json().get("content", []):
                    isrc = (f.get("isrc") or "").upper()
                    if isrc and isrc not in uit:
                        uit[isrc] = f
                break
            except Exception as e:
                print(f"  [Rust] ReccoBeats-fout: {e}")
                time.sleep(3)
        time.sleep(0.3)
    return uit


def bepaal_rust(session, playlist_id: str, playlist_log: dict):
    """Vult "rust" aan voor nummers die het nog niet hebben of alleen een schatting hebben."""
    try:
        tracks = list(session.playlist(playlist_id).tracks_paginated())
    except Exception as e:
        print(f"[Rust] Kon Nachtradio niet ophalen: {e}")
        return
    te_doen = {}
    for t in tracks:
        e = playlist_log.get(str(t.id))
        if not isinstance(e, dict):
            continue
        if not e.get("isrc") and getattr(t, "isrc", None):
            e["isrc"] = t.isrc.upper()
        if "rust" in e and e.get("rust_bron") != "schatting":
            continue
        if e.get("isrc"):
            te_doen[e["isrc"]] = e
        else:
            e["rust"], e["rust_bron"] = schatting(e), "schatting"
    if not te_doen:
        print("[Rust] Alle nummers hebben al een rustniveau")
        return
    features = _recco(list(te_doen))
    gemeten = geschat = 0
    for isrc, e in te_doen.items():
        f = features.get(isrc)
        if f and f.get("energy") is not None:
            e["intensiteit"] = intensiteit(f)
            e["rust"] = niveau(e["intensiteit"])
            e["rust_bron"] = "reccobeats"
            gemeten += 1
        else:
            e["rust"], e["rust_bron"] = schatting(e), "schatting"
            geschat += 1
    print(f"[Rust] {gemeten} nummers gemeten via ReccoBeats, {geschat} geschat uit bron en genres")


def verdeling(playlist_log: dict) -> str:
    tel = {n: 0 for n in range(1, 6)}
    for e in playlist_log.values():
        if isinstance(e, dict) and e.get("rust") in tel:
            tel[e["rust"]] += 1
    return ", ".join(f"niveau {n}: {tel[n]}" for n in tel)


def sync_rust_playlists(session, state: dict, playlist_log: dict):
    """Zet Avond en Nacht gelijk met de rustige nummers die nu in Nachtradio staan."""
    ids = state.setdefault("rust_playlists", {})
    for naam, (titel, max_niveau, beschrijving) in RUST_PLAYLISTS.items():
        try:
            if not ids.get(naam):
                pl = session.user.create_playlist(titel, beschrijving)
                ids[naam] = pl.id
                print(f"[Rust] Playlist '{titel}' aangemaakt: {pl.id}")
            pl = session.playlist(ids[naam])
            wil = [tid for tid, e in playlist_log.items()
                   if isinstance(e, dict) and isinstance(e.get("rust"), int) and e["rust"] <= max_niveau]
            wil_set = set(wil)
            huidig = [str(t.id) for t in pl.tracks_paginated()]
            weg, gezien = [], set()
            for idx, tid in enumerate(huidig):
                if tid not in wil_set or tid in gezien:
                    weg.append(idx)
                gezien.add(tid)
            if weg:
                for i in range(0, len(weg), 50):
                    pl.remove_by_indices(sorted(weg, reverse=True)[i:i + 50])
                    pl = session.playlist(ids[naam])
            erbij = [tid for tid in wil if tid not in gezien]
            if erbij:
                for i in range(0, len(erbij), 50):
                    pl.add([int(t) for t in erbij[i:i + 50]])
            print(f"[Rust] {titel}: {len(weg)} eruit, {len(erbij)} erbij, nu {len(wil)} nummers")
        except Exception as e:
            print(f"[Rust] {titel} bijwerken mislukt: {e}")
