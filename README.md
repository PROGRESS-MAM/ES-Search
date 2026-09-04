# Searcher

Modul zum Durchsuchen von Clip-Metadaten – über die Metadata-API oder über die Parquet-Datei
`all_clips_all_metadata.parquet` auf dem SMB-Share.

## Installation

Einmal pro Maschine Flow-API URL linken:

```bash
pip config set global.extra-index-url https://artifacts.editshare.com/artifactory/api/pypi/editshare-pypi-public/simple
```

Danach den Searcher installieren:

```bash
# nur Datei (Parquet)
pip install "searcher @ git+https://github.com/PROGRESS-MAM/ES-Search.git@main"

# mit API
pip install "searcher[api] @ git+https://github.com/PROGRESS-MAM/ES-Search.git@main"
```

Zur Entwicklung am Searcher selbst im Repo-Wurzelverzeichnis:

```bash
pip install -e ".[api]"
```

## Voraussetzungen

Die Datei-Datenquelle mountet den SMB-Share per `net use` und ist damit **Windows-only**.
Die API-Datenquelle läuft plattformunabhängig. Den Pfad zur Datei kennt das Modul selbst.

`cred.env` für die Datei-Datenquelle:

```env
SMB_HOST=server ip
SMB_USER=benutzer
SMB_PASSWORD=geheim
```

`SMB_USER` und `SMB_PASSWORD` sind optional – fehlen sie, wird kein `net use` ausgeführt und der
Pfad muss bereits erreichbar sein.

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
    print(f"\r{message:<80}", end="", flush=True)

cred_path = Path(__file__).parent / "cred.env"

searcher.link(
    "file",                                                 # "file" oder "api"
    cred_path,                                              # Pfad zur cred.env
    on_progress=print_progress,                             # optional
    api_link=lambda: tb_link_api(cred_path, "metadata"),    # nur für "api"
)

for search in searches:
    match, progress, error = searcher.find(search)

    if error:
        print(error)
        continue
```

`link(...)` einmal aufrufen, danach beliebig viele `find(...)`. Jede Suche läuft immer über den
kompletten Datenbestand.

Rückgabe von `find`:

| Wert | Inhalt |
| --- | --- |
| `match` | Liste der Ergebniszeilen in Reihenfolge der `return_fields` |
| `progress` | Statustext |
| `error` | Text inkl. Traceback oder `None`, Teiltreffer bleiben in `match` |

Ist ein `on_progress`-Callback gesetzt, gibt der Searcher die Abschlussmeldung dort bereits selbst
aus.

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

- `name` – für Statusmeldungen und Ergebnisdateinamen
- `request_fields` – Bedingungen `(feld, operator, wert)`, verknüpft mit `"and"` oder `"or"`
- `return_fields` – Felder pro Treffer, Mehrfachwerte werden mit `; ` verbunden

Feldnamen sind unabhängig von Groß-/Kleinschreibung. Ein Name ohne Punkt trifft jedes Feld mit
diesem Namen, egal wie tief es liegt. Ein Name mit Punkt ist der vollständige Pfad ab der Wurzel;
findet sich dort nichts, wird zusätzlich unter `custom_metadata` mit Unterstrich statt Punkt
gesucht (`foo.bar` → `custom_metadata.foo_bar`). Beide Datenquellen lösen Feldnamen gleich auf.

### Operatoren

| Operator | Bedeutung |
| --- | --- |
| `is` | exakte Übereinstimmung, Groß-/Kleinschreibung ignoriert |
| `contains` | Teilstring; als Wert ist auch eine Liste erlaubt, Treffer sobald ein Eintrag passt |
| `>` `<` `>=` `<=` | numerischer Vergleich, nicht konvertierbare Werte werden übersprungen |

Jeder Operator lässt sich negieren: `is not`, `contains not`, `not >`, `not <`, `not >=`, `not <=`.
Die Negation kehrt das Ergebnis der Bedingung um; ein fehlendes Feld bleibt dabei `False`.

Ein Feld gilt als Treffer, sobald **einer** seiner Werte passt. Fehlendes oder leeres Feld ist
`False`. Ein unbekannter Operator ist ebenfalls `False`, ohne Fehlermeldung – Tippfehler zeigen
sich als „0 Treffer“.

`"and"` / `"or"` werden strikt von links nach rechts ausgewertet, ohne Klammern und ohne Präzedenz:

```python
(A, "and", B, "or", C)     #  ->  (A and B) or C
(A, "or",  B, "and", C)    #  ->  (A or B) and C
```

## Datei-Datenquelle

Die Parquet-Datei wird blockgruppenweise gelesen. Pro Blockgruppe läuft zuerst ein vektorisierter
Vorfilter über die Spalten der Bedingungen, nur die Kandidatenzeilen werden anschließend
zeilenweise exakt geprüft. Das Ergebnis ist identisch zur API-Suche, nur deutlich schneller.

- Der Vorfilter greift nur bei `is` und `contains` auf Textspalten, alle anderen Fälle lassen
  sämtliche Zeilen als Kandidaten durch.
- Kommt kein Feld der Suche in der Datei vor, endet die Suche direkt ohne Treffer.
- Der Fortschritt meldet Blockgruppe, vorgefilterte Clips und Kandidaten; bei der API dagegen
  den laufenden Clip.

## Beispielimplementierung

```bash
python sample.py
```

`sample.py` zeigt einen vollständigen Caller mit Konfiguration, Suchdefinitionen, Logging und
CSV-Ausgabe. Treffer landen in `searches/<name>_result_<zeitstempel>.csv`, Meldungen in
`searcher.log`. Alle Pfade werden in `sample.py` gesetzt.

## Updates in anderen Repos

```bash
pip install --force-reinstall --no-deps "searcher @ git+https://github.com/PROGRESS-MAM/ES-Searcher.git@main"
```
