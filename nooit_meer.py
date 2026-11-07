"""
"Nooit meer" vanuit Home Assistant: zet een nummer (en eventueel de artiest en genres)
in blokkades.txt. Daarna draait main.py in opkuismodus en verdwijnt het uit de playlist.

De workflow geeft de vraag door in de omgevingsvariabele NOOIT_MEER (JSON):
  {"artiest": "Gorki", "titel": "Beste Bill", "id": "1475286",
   "artiest_blokkeren": false, "genres": ["dutch rock"]}
"""
import json
import os
import re
from pathlib import Path

BESTAND = Path("blokkades.txt")


def schoon(waarde, max_len=150) -> str:
    """Eén regel, geen kopjes of scheidingstekens die het bestand kunnen breken."""
    t = re.sub(r"\s+", " ", str(waarde or "")).strip()
    t = t.replace("|", "/").lstrip("[#").strip()
    return t[:max_len]


def voeg_toe(regels: list[str], sectie: str, waarde: str) -> bool:
    kop = f"[{sectie}]"
    start = next((i for i, r in enumerate(regels) if r.strip().lower() == kop), None)
    if start is None:
        while regels and not regels[-1].strip():
            regels.pop()
        regels += ["", "", kop, waarde]
        return True
    einde = next((i for i in range(start + 1, len(regels)) if re.match(r"^\s*\[.+\]\s*$", regels[i])), len(regels))
    if any(r.strip().lower() == waarde.lower() for r in regels[start + 1:einde]):
        return False
    laatste = start
    for i in range(start + 1, einde):
        if regels[i].strip():
            laatste = i
    regels.insert(laatste + 1, waarde)
    return True


def main():
    vraag = json.loads(os.environ.get("NOOIT_MEER") or "{}")
    artiest = schoon(vraag.get("artiest"))
    titel = schoon(vraag.get("titel"))
    tidal_id = re.sub(r"\D", "", str(vraag.get("id") or ""))[:20]
    regels = BESTAND.read_text(encoding="utf-8").splitlines()
    gedaan = []

    if artiest and titel:
        if voeg_toe(regels, "nummers", f"{artiest.lower()} | {titel.lower()} | {tidal_id}".rstrip(" |")):
            gedaan.append(f"nummer {artiest} - {titel}")
    if artiest and vraag.get("artiest_blokkeren"):
        if voeg_toe(regels, "artiesten", artiest.lower()):
            gedaan.append(f"artiest {artiest}")
    for g in (vraag.get("genres") or [])[:5]:
        g = schoon(g, 60).lower().replace("-", " ")
        if len(g) >= 3 and voeg_toe(regels, "genres", g):
            gedaan.append(f"genre {g}")

    BESTAND.write_text("\n".join(regels) + "\n", encoding="utf-8")
    samenvatting = ", ".join(gedaan) or "niets nieuws (stond er al)"
    print(f"[Nooit meer] {samenvatting}")
    # Voor het commitbericht in de workflow
    Path(os.environ.get("SAMENVATTING_BESTAND", "nooit_meer_samenvatting.txt")).write_text(samenvatting[:200], encoding="utf-8")


if __name__ == "__main__":
    main()
