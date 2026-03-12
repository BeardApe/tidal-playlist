"""
Leest TIDAL_SESSION_JSON uit env, normaliseert de {"data": value} wrappers,
en schrijft het resultaat naar /tmp/tidal_session.json.
"""
import os
import json
import pathlib

raw_str = os.environ["TIDAL_SESSION_JSON"]

# Debug: toon exact wat we ontvangen
print(f"Lengte: {len(raw_str)}")
print(f"Eerste 50 tekens (repr): {repr(raw_str[:50])}")
print(f"Laatste 20 tekens (repr): {repr(raw_str[-20:])}")

# Verwijder alle witruimte rondom de string
cleaned = raw_str.strip()

raw = json.loads(cleaned)
normalized = {
    k: (v["data"] if isinstance(v, dict) and "data" in v else v)
    for k, v in raw.items()
}
pathlib.Path("/tmp/tidal_session.json").write_text(json.dumps(normalized))
print("Sessie geschreven:", list(normalized.keys()))
