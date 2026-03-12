"""
Schrijft TIDAL_SESSION_JSON naar /tmp/tidal_session.json.
"""
import os
import pathlib

raw_str = os.environ["TIDAL_SESSION_JSON"].strip()
pathlib.Path("/tmp/tidal_session.json").write_text(raw_str)
print("Sessie geschreven, lengte:", len(raw_str))
