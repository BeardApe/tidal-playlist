"""
setup.py — Eénmalig lokaal uitvoeren om je Tidal sessie op te slaan.

Wat dit doet:
1. Opent een browser-link om in te loggen bij Tidal
2. Slaat de sessie op als session.json
3. Print de JSON-inhoud die je als GitHub Secret moet instellen

Uitvoeren:
    pip install -r requirements.txt
    python setup.py
"""

import json
from pathlib import Path
import tidalapi

def main():
    session = tidalapi.Session()

    print("\nTidal authenticatie starten...")
    print("Een browser-link wordt gegenereerd — klik erop en log in.\n")

    # OAuth2 login — opent browser of geeft een link
    session.login_oauth_simple()

    if session.check_login():
        print("\n✓ Succesvol ingelogd!")

        # Sessie opslaan
        session.save_session_to_file(Path("session.json"))

        # Print de JSON voor GitHub Secrets
        with open("session.json") as f:
            data = json.load(f)

        print("\n" + "="*60)
        print("KOPIEER DIT ALS GITHUB SECRET → TIDAL_SESSION_JSON:")
        print("="*60)
        print(json.dumps(data))
        print("="*60)
        print("\nOok nodig:")
        print(f"  TIDAL_PLAYLIST_ID = (zie hieronder)")
        print()

        # Zoek bestaande playlists
        user = session.user
        playlists = user.playlists()
        print("Jouw Tidal playlists:")
        for p in playlists:
            print(f"  ID: {p.id}  |  Naam: {p.name}")

        print("\nMaak een nieuwe lege playlist aan op Tidal als je die nog niet hebt,")
        print("en gebruik het ID hiervan als TIDAL_PLAYLIST_ID.")

    else:
        print("✗ Login mislukt. Probeer opnieuw.")

if __name__ == "__main__":
    main()
