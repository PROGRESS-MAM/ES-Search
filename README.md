# Searcher

Modul zum Durchsuchen von Clip-Metadaten – über die Metadata-API oder über die CSV-Datei
`all_clips_all_metadata.csv` auf dem SMB-Share.

## Installation

Einmal pro Maschine Flow-API URL linken:

```bash
pip config set global.extra-index-url https://artifacts.editshare.com/artifactory/api/pypi/editshare-pypi-public/simple
```

Danach den Searcher installieren:

```bash
# nur CSV
pip install "searcher @ git+https://github.com/PROGRESS-MAM/ES-Searcher.git@main"

# mit API
pip install "searcher[api] @ git+https://github.com/PROGRESS-MAM/ES-Searcher.git@main"
```

Zur Entwicklung am Searcher selbst im Repo-Wurzelverzeichnis:

```bash
pip install -e ".[api]"
```

## Voraussetzungen

Die CSV-Datenquelle mountet den SMB-Share per `net use` und ist damit **Windows-only**.
Die API-Datenquelle läuft plattformunabhängig.

`cred.env` für die CSV-Datenquelle:

```env
CSV_HOST=server ip
CSV_USER=benutzer
CSV_PASSWORD=geheim
```

Für die API-Datenquelle zusätzlich:

```env
FLOW_HOST=server ip
FLOW_USER=benutzer
FLOW_PASSWORD=geheim
```

## Verwendung

```python
from pathlib import Path
from toolbox import tb_link_api
import searcher

def print_progress(message):
    print(f"\r{message:<60}", end="", flush=True)

cred_path = Path(__file__).parent / "cred.env"

searcher.link(
    "csv",                                                  # "csv" oder "api"
    cred_path,                                              # Pfad zur cred.env
    offset=0,                                               # Zahl oder False
    limit=False,                                            # Zahl oder False = alle
    on_progress=print_progress,                             # optional
    api_link=lambda: tb_link_api(cred_path, "metadata"),    # nur für "api"
)

for search in searches:
    match, progress, error = searcher.find(search)

    if error:
        print(error)
        continue

    print(progress)
```

`link(...)` einmal aufrufen, danach beliebig viele `find(...)`. Pro Suche lassen sich
`offset` und `limit` überschreiben: `searcher.find(search, offset=0, limit=1000)`.

Rückgabe von `find`:

| Wert | Inhalt |
| --- | --- |
| `match` | Liste der Ergebniszeilen in Reihenfolge der `return_fields` |
| `progress` | Statustext |
| `error` | Text inkl. Traceback oder `None`, Teiltreffer bleiben in `match` |

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

- `name` – für Statusmeldungen und Ergebnisordner
- `request_fields` – Bedingungen `(feld, operator, wert)`, verknüpft mit `"and"` oder `"or"`
- `return_fields` – Felder pro Treffer, Mehrfachwerte werden mit `; ` verbunden

Feldnamen sind unabhängig von Groß-/Kleinschreibung. Bei der CSV zählt auch das letzte Segment
punktierter Spaltennamen, bei der API greift `feld.unterfeld` in verschachtelte Strukturen.

### Operatoren

| Operator | Bedeutung |
| --- | --- |
| `is` | exakte Übereinstimmung, Groß-/Kleinschreibung ignoriert |
| `contains` | Teilstring; als Wert ist auch eine Liste erlaubt, Treffer sobald ein Eintrag passt |
| `>` `<` `>=` `<=` | numerischer Vergleich, nicht konvertierbare Werte werden übersprungen |

Ein Feld gilt als Treffer, sobald **einer** seiner Werte passt. Fehlendes oder leeres Feld ist
`False`. Ein unbekannter Operator ist ebenfalls `False`, ohne Fehlermeldung – Tippfehler zeigen
sich als „0 Treffer“.

`"and"` / `"or"` werden strikt von links nach rechts ausgewertet, ohne Klammern und ohne Präzedenz:

```python
(A, "and", B, "or", C)     #  ->  (A and B) or C
(A, "or",  B, "and", C)    #  ->  (A or B) and C
```

## Beispielimplementierung

```bash
python sample.py
```

`sample.py` zeigt einen vollständigen Caller mit Konfiguration, Suchdefinitionen, Logging und
CSV-Ausgabe. Treffer landen in `searches/<name>/result_<zeitstempel>.csv`, Meldungen in
`searcher.log`. Alle Pfade werden in `sample.py` gesetzt.

## Neues Release

1. In `searcher/searcher.py` die Version erhöhen:

   ```python
   app_version = "0.7"
   ```

2. Changes committen und pushen.

## Updates in anderen Repos

```bash
pip install --force-reinstall --no-deps "searcher @ git+https://github.com/PROGRESS-MAM/ES-Searcher.git@main"
```