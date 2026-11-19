"""Refresh the snapshot from the public demonstration ThingSpeak channel."""

from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://api.thingspeak.com/channels/3572190/feeds.csv?results=8000"
TARGET = Path(__file__).resolve().parent / "thingspeak_snapshot.csv"

with urlopen(Request(URL, headers={"User-Agent": "portfolio-analysis/1.0"}), timeout=30) as response:
    data = response.read()
if not data.startswith(b"created_at,entry_id,"):
    raise ValueError("A resposta não tem o formato CSV esperado do ThingSpeak")
TARGET.write_bytes(data)
print(f"Snapshot público salvo em {TARGET.name}: {data.count(bytes([10])) - 1} leituras")
