# CLAUDE.md: Nachtradio en Ochtendjazz

Deze repo vult automatisch twee Tidal-playlists van PJ (Pieter Jan Rosiers, Gent).
Lees dit eerst. Het vat samen wat in eerdere sessies is gebouwd, beslist en fout liep.

## Over PJ

- Absolute beginner met GitHub en Python, werkt op Windows. Leg technische dingen eenvoudig uit, in het Nederlands (Vlaams).
- Schrijf kort, droog en concreet. Geen em-dashes, geen pakkende antithese-zinnen, geen AI-woorden ("ritueel", "reflex" en zo).
- Hij wil één definitief antwoord, geen lijst varianten.
- Hij wil dat je zelf pusht en zelf de run start. Laat hem geen code kopiëren als je het zelf kan doen.
- Repo: `BeardApe/tidal-playlist` (publiek). Er staan geen geheimen in de code, alleen in GitHub Secrets.

## De twee playlists

| Playlist | Tidal-ID | Script | Workflow | Ritme |
|---|---|---|---|---|
| Nachtradio (in Home Assistant de knop "Indie") | `3defe40a-5161-4933-8e58-8b38c6c024e5` (secret `TIDAL_PLAYLIST_ID`) | `main.py` | `daily.yml` | dinsdag 06:00 UTC |
| Ochtendjazz | `efc92d5f-7912-453b-9576-8a63bde1dd29` (in `jazz.py`) | `jazz.py` | `jazz.yml` | zondag 06:00 UTC |

Nachtradio is achtergrondmuziek die thuis de hele dag speelt. Ochtendjazz is zachte, trage cocktailbarjazz om wakker te worden (afwisselend zang en instrumentaal, uit een vaste lijst zachte albums).

## Muzieksmaak (Nachtradio)

- Wel: rustig, intiem, licht melancholisch. Trip-hop, downtempo, warme folk en singer-songwriters, soulvol en jazzy, dream pop, queer stemmen (fan van Dressed Like Boys), Belgische artiesten, nostalgie 90s/00s.
- Niet: rap (absoluut niet), stevige of rauwe rock, punk, metal, emo, techno, repetitieve minimal/IDM, ambient. Rock via Studio Brussel (Queens of the Stone Age, Foo Fighters) mag wel.
- Volgt de radioprogramma's Duyster (Radio 1, maandag 22-24u) en Vuurland. "Vuurland" is het programma op Studio Brussel (zondag 20-22u), niet de 24/7-zender Vuurland.

## Hoe `main.py` werkt (één run)

1. `blokkades.txt` inlezen (genres en artiesten).
2. Tidal-sessie laden uit `/tmp/tidal_session.json` (geschreven door `normalize_session.py` uit secret `TIDAL_SESSION_JSON`, geneste tidalapi-vorm, niet normaliseren).
3. `remove_old_tracks`: nummers ouder dan 30 dagen uit de playlist.
4. `backfill_playlist_log`: ontbrekende artiest/titel aanvullen en status opruimen voor nummers die niet meer in de playlist staan.
5. `purge_unwanted`: alles uit de playlist halen dat nu geblokkeerd is (artiest, genre, genre per bron, stopgezette bron). Genres die nog niet bekend zijn, worden eenmalig opgezocht.
6. Kandidaten verzamelen:
   - Spotify-playlists van curatoren (`SPOTIFY_PLAYLISTS`, client-credentials, max. 20 willekeurig per lijst).
   - Last.fm: 4 willekeurige `SEED_ARTISTS`, telkens 2 vergelijkbare artiesten, 3 topnummers.
   - Radioprogramma's (`RADIO_PROGRAMS`): volledige tracklist van elke nieuwe uitzending van Duyster en Vuurland, via relisten.be (de officiële VRT-afspeellijst per dag). Verwerkte uitzendingen staan in `state["programs_done"]`, tot 14 dagen terug.
   - Internationale zenders (`STATIONS`): Radio Paradise Mellow Mix, SomaFM Lush, Double J (ABC-API), The Current (JSON in de pagina). Per run max. 25 nieuwe per zender.
7. Genres bepalen: Spotify-genres, anders Last.fm-tags (Spotify laat veel genres leeg). Dan filteren op genre, genre per bron en artiest. Seed-artiesten zijn immuun voor genrefilters, niet voor de artiestenblokkade.
8. Elk nummer opzoeken op Tidal, dubbels overslaan (`seen` onthoudt alles ooit toegevoegd, ook na uitrouleren), toevoegen.
9. `state.json` en `run.log` worden door de workflow teruggecommit.

Er is geen limiet per run. Rotatie gebeurt op leeftijd (30 dagen). De playlist schommelt rond de 1.000 tot 1.200 nummers.

## Filters

- `blokkades.txt`: gewone genres en artiesten. PJ past dit zelf aan via het dashboard. Een genre matcht als deelwoord ("rock" pakt ook "indie rock"). Artiesten matchen exact, in kleine letters.
- In `main.py`:
  - `STRICT_SOURCES` (The Current, Double J, WFUV, WXPN, NPR, KCRW en "onbekend"): alles met rock, punk, garage, grunge, metal, hardcore of emo is geblokkeerd, en nummers zonder genre-info komen er niet in. Die zenders brachten veel rock binnen.
  - `BLOCKED_SOURCES`: stopgezette bronnen waarvan alles gepurged wordt (FIP-Live, Vuurland-zender, KEXP-NewThisWeek).
- Een bron schrappen = uit de lijst halen én in `BLOCKED_SOURCES` zetten, zodat de bestaande nummers ook weg gaan.

## `state.json`

- `seen`: `{"artiest|titel": {date, source}}`. Nooit opnieuw toevoegen wat hierin staat.
- `playlist_log`: `{tidal_id: {date, artist, title, source, genres}}`. Wat nu in de playlist staat. `date` stuurt de rotatie.
- `programs_done`: per programma de verwerkte uitzendingsdata.
- `migrated_vuurland_program`: eenmalige migratie is gebeurd.
- Bron "onbekend" = nummer dat niet (meer) herleidbaar is tot een bron. Krijgt een datum zodat het uitrouleert.

## Workflows

- `daily.yml` (Nachtradio): dinsdag 06:00 UTC, handmatig, en bij elke push die `main.py`, `blokkades.txt` of `requirements.txt` wijzigt. Pushen is dus de manier om een run te starten; de "Run workflow"-API is niet toegankelijk met de tokens die we krijgen.
- `jazz.yml` (Ochtendjazz): zondag, en bij push van `jazz.py` of de workflow. Status in `state_jazz.json`.
- `spotify_naar_tidal.yml` en `youtube_naar_tidal.yml`: handmatige hulpjes om een Spotify-lijst of een YouTube-tracklist (DJ-sets, hele YouTube-playlists) naar een Tidal-playlist over te zetten. YouTube gebruikt secret `YOUTUBE_API_KEY`.
- `probe.yml`: haalt de URL's uit `probe/urls.txt` op en commit ze in `probe/out/`. Gebruik dit om een nieuwe bron te testen: de sandbox van Claude kan veel sites niet bereiken, GitHub Actions wel. Ruim `probe/out` daarna op.
- `cleanup.yml` / `cleanup.py`: oude eenmalige opkuis, overbodig sinds `purge_unwanted`.
- Installatie: vaste versies in `requirements.txt`, pip-cache, drie pogingen bij een PyPI-hapering.

Secrets: `TIDAL_SESSION_JSON`, `TIDAL_PLAYLIST_ID`, `LASTFM_API_KEY`, `LASTFM_API_SECRET`, `LASTFM_USERNAME` (Tinselboy), `LASTFM_PASSWORD`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `YOUTUBE_API_KEY`. Workflow permissions staan op read and write.

Verloopt de Tidal-sessie, dan draait PJ lokaal `python setup.py` en plakt de JSON-uitvoer als nieuwe `TIDAL_SESSION_JSON`.

## Dashboard

- `docs/index.html` op GitHub Pages: https://beardape.github.io/tidal-playlist/ (`docs/jazz.html` voor Ochtendjazz).
- Leest `state.json` via raw.githubusercontent.com. Tabs: huidige playlist (met rotatiebalk), uitgerouleerd, bronnen, genres, blokkades.
- Blokkeren met één klik: het dashboard past `blokkades.txt` aan via de GitHub-API met een fine-grained token van PJ (alleen deze repo, Contents read/write), bewaard in localStorage. Die commit start meteen een run.
- Volgende run wordt berekend als dinsdag 06:00 UTC.

## Thuis afspelen

Home Assistant speelt Nachtradio via Music Assistant op een Sonos-syncgroep ("Alle speakers"), via `script.speel_playlist` (knop "Indie") en `script.muziek_poging`. Music Assistant houdt een kopie van de playlist bij en vernieuwt die niet meteen. Hoort PJ nummers die al verwijderd zijn of nooit in de lijst stonden, vergelijk dan het aantal in Music Assistant met het aantal op Tidal (zie "Huidig in playlist" in `run.log`) en laat hem de playlist in Music Assistant vernieuwen.

## Werkwijze voor Claude

- Clone, wijzig, commit en push naar `main`. Commitberichten in het Nederlands.
- Controleer `main.py` met `python -c "import ast; ast.parse(open('main.py').read())"`. Test scrapers offline op opgehaalde pagina's voor je pusht.
- Wacht op de run en lees het resultaat uit git (`git fetch` en `git show origin/main:run.log`), niet via raw.githubusercontent.com: die cachet en toonde eerder verouderde data.
- Bij twijfel over impact van een filter: simuleer eerst op `state.json` hoeveel nummers er zouden verdwijnen en meld dat.
- Elke run voegt nieuwe nummers toe. Veel testruns na elkaar laten de playlist groeien; vermijd onnodige runs.
- Klaagt PJ over een nummer, zoek het eerst op in `state.json` en in de geschiedenis van `run.log`, zodat je weet uit welke bron het komt voor je een filter verandert.

## Geschiedenis in het kort

- Begon met Spotify-kopieën van Vuurland en Duyster; die bleken stilgevallen. Nu via relisten.be, per uitzending.
- FIP en KEXP zijn geschrapt (te rommelig of te veel rock). Ook de 24/7-zender Vuurland is geschrapt; alleen het programma telt.
- Moderat, Nils Frahm, Boards of Canada, Four Tet en Röyksopp zijn uit de seeds gehaald: hun Last.fm-verwanten waren minimal/IDM.
- Oktober 2026: 257 rocknummers van The Current, Double J en onbekende herkomst gepurged; daarna `STRICT_SOURCES` ingevoerd.
