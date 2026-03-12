"""
Leest TIDAL_SESSION_JSON uit env, normaliseert de {"data": value} wrappers,
en schrijft het resultaat naar /tmp/tidal_session.json.
"""
import os
import json
import pathlib

raw = json.loads(os.environ["TIDAL_SESSION_JSON"])
normalized = {
    k: (v["data"] if isinstance(v, dict) and "data" in v else v)
    for k, v in raw.items()
}
pathlib.Path("/tmp/tidal_session.json").write_text(json.dumps(normalized))
print("Sessie geschreven:", list(normalized.keys()))
