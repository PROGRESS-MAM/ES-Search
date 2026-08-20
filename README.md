# Searcher

Modul zum Durchsuchen von Clip-Metadaten – entweder über die Metadata-API oder über die CSV-Datei
`all_clips_all_metadata.csv` auf dem SMB-Share.

## Verwendung

```python
from pathlib import Path
import Searcher as searcher

def print_progress(message):
    print(f"\r{message:<60}", end="", flush=True)

searcher.link(
    "csv",                                  # "csv" oder "api"
    Path(__file__).parent / "cred.env",     # Pfad zur cred.env
    offset=0,                               # Zahl oder False
    limit=False,                            # Zahl oder False = alle Clips/Rows
    on_progress=print_progress,             # optional, sonst None
)

for search in searches:
    match, progress, error = searcher.find(search)

    if error:
        print(error)
        continue

    print(progress)
    for row in match:
        print(row)
```

- `link(...)` einmal aufrufen, danach beliebig viele `find(...)`-Aufrufe.
- `find(search, offset=..., limit=...)` kann die Werte aus `link(...)` pro Suche überschreiben.
- Rückgabe: `match` = Liste der Ergebniszeilen in Reihenfolge der `return_fields`,
  `progress` = Statustext, `error` = Text oder `None`. Bei einem Fehler bleiben bereits
  gefundene Treffer in `match` erhalten.
- Eine vollständige Suche über alle Rows dauert rund 2 Minuten.

## Aufbau einer Suche

```python
searches = [
    {
        "name": "My Search",
        "request_fields": (
            ("display_backups", "is", "LTO01234"),
            "and",
            ("media_space_name", "contains", "search"),
        ),
        "return_fields": ("clip_id", "media_space_name", "display_name"),
    }
]
```

- `name` – wird für Statusmeldungen und Ergebnisordner verwendet
- `request_fields` – Tupel aus Bedingungen `(feld, operator, wert)`, verknüpft mit `"and"` oder `"or"`
- `return_fields` – Felder, die pro Treffer zurückgegeben werden (Mehrfachwerte werden mit `; ` verbunden)

### Operatoren

| Operator | Bedeutung |
| --- | --- |
| `is` | exakte Übereinstimmung, Groß-/Kleinschreibung wird ignoriert |
| `contains` | Teilstring, Groß-/Kleinschreibung wird ignoriert; als Wert ist auch eine Liste/ein Tupel erlaubt (Treffer, sobald ein Eintrag passt) |
| `>` `<` `>=` `<=` | numerischer Vergleich; nicht konvertierbare Werte werden übersprungen |

Ein Feld gilt als Treffer, sobald **einer** seiner Werte die Bedingung erfüllt – Felder können
mehrfach vorkommen bzw. mehrere Werte enthalten. Fehlt das Feld oder ist es leer, ist die
Bedingung `False`.

**Verknüpfung mit `"and"` / `"or"`**

Die Auswertung erfolgt strikt von links nach rechts, ohne Klammerung und ohne Operator-Präzedenz:

```python
(A, "and", B, "or", C)     #  ->  (A and B) or C
(A, "or",  B, "and", C)    #  ->  (A or B) and C
```

## Beispielimplementierung

`sample.py` im Wurzelverzeichnis zeigt einen vollständigen Caller: Konfiguration, Suchdefinitionen,
Logging und CSV-Ausgabe. Aufruf:

```bash
python sample.py
```

Die Treffer landen in `searches/<name>/result_<zeitstempel>.csv`, Statusmeldungen und Fehler
zusätzlich in `searcher.log`. Beide Pfade sowie der Pfad zur `cred.env` werden in `sample.py`
gesetzt.
