# Searcher

Modul zum Durchsuchen von Clip-Metadaten: produktive Parquet-Dateisuche (`file`) oder FLOW Search-API (`api`, ausschließlich Cached Search).
## Installation

Für die optionale TOOLBOX-Installation die EditShare-Paketquelle konfigurieren:

```bash
pip config set global.extra-index-url https://artifacts.editshare.com/artifactory/api/pypi/editshare-pypi-public/simple
```

```bash
# nur Datei (Parquet)
pip install "searcher @ git+https://github.com/PROGRESS-MAM/ES-Search.git@main"

# mit API-Unterstützung
pip install "searcher[api] @ git+https://github.com/PROGRESS-MAM/ES-Search.git@main"

# im Repository für Entwicklung
pip install -e ".[api]"
```

## Voraussetzungen

`file`: Windows, erreichbarer SMB-Share, Parquet-Datei und `cred.env` mit:

```env
SMB_HOST=server ip
SMB_USER=benutzer
SMB_PASSWORD=geheim
```

`SMB_USER` und `SMB_PASSWORD` sind optional. Ohne sie muss der Share bereits erreichbar sein.
Der Datei-Modus mountet den Share bei Bedarf per `net use` und verwendet intern
`SMB File Exchange/Metadata_File/all_clips_all_metadata.parquet`.

`api`: FLOW-Gateway und installierte TOOLBOX mit FLOW Search-Wrapper und `cred.env` mit:

```env
FLOW_HOST=server ip
FLOW_USER=benutzer
FLOW_PASSWORD=geheim
```

`FLOW_HOST` ist der Hostname bzw. die IP des FLOW-Gateways; der Search-Wrapper verbindet sich
über Port 8006. Zugangsdaten niemals im Code ablegen. Achtung: Die hier bereitgestellte
Version des FLOW-Wrappers deaktiviert die TLS-Zertifikatsprüfung in der Verbindung;
setze sie nur in einer entsprechend abgesicherten Umgebung ein.

## Verwendung

```python
from pathlib import Path
import searcher

cred_path = Path(__file__).parent / "cred.env"
from toolbox import tb_link_api

searcher.link("api", cred_path, on_progress=print,
              api_link=lambda: tb_link_api(cred_path, "search"))  # oder "file"

search = {
    "name": "Meine Suche",
    "request_fields": (("MEDIA_SPACES_NAMES", "is", "Oury Jalloh Render"),),
    "return_fields": ("clip_id", "display_name", "userpath"),
}
match, progress, error = searcher.find(search)
if error:
    print(error)
else:
    print(progress)
```

`link(...)` einmal aufrufen, dann beliebig viele `find(...)`. Im API-Modus verwendet `link`
`tb_link_api(cred_path, "search")` der TOOLBOX und damit den gelieferten FLOW Search-Wrapper.
`api_link` ist ein optionaler Callback; fehlt er, stellt der Searcher dieselbe TOOLBOX-Verbindung
selbst her. Die Metadata-API wird nicht verwendet. Es wird keine direkte HTTP-Session im
Searcher angelegt.

| Rückgabewert | Bedeutung |
| --- | --- |
| `match` | Ergebniszeilen in Reihenfolge der `return_fields`; im Fehlerfall bereits vollständig bearbeitete Seiten |
| `progress` | Abschlusstext bei Erfolg |
| `error` | Fehlertext inkl. Traceback oder `None` |

## Suchdefinition

Beide Datenquellen verwenden dasselbe Suchformat und dieselbe Ergebnisverarbeitung.
`request_fields` besteht aus Tupeln `(feld, operator, wert)` mit `"and"`/`"or"` dazwischen.
Der Aufrufer gibt die für die jeweils gewählte Quelle gültigen Feldnamen direkt an;
der Searcher übersetzt keine Feldnamen zwischen `file` und `api`.
`"and"` und `"or"` werden strikt von links nach rechts, ohne Klammern und Präzedenz,
ausgewertet: `(A, "and", B, "or", C)` bedeutet `(A and B) or C`.
`return_fields` bezeichnet die Felder oder Feldpfade aus den Ergebnisdatensätzen,
die in der CSV erscheinen sollen; Mehrfachwerte werden mit `; ` verbunden.
Für `api` muss jeder Name in `request_fields` im Search-Fields-Index der Vorlage
vorkommen. `return_fields` sind davon unabhängig und werden aus den vollständigen
Metadatensätzen gelesen. Für `file` bleiben die Namen der Parquet-Felder maßgeblich.

Die Operatoren stehen in **einer gemeinsamen Zuordnung** für beide Modi. Unterstützt: `is`, `is not`, `contains`, `contains not`,
`starts_with`, `ends_with`, `>`, `<`, `>=`, `<=`, `not >`,
`not <`, `not >=`, `not <=`. Für `contains` ist auch eine Liste von Werten erlaubt
(Treffer bei einem beliebigen Eintrag). In `api` muss der jeweilige Operator in den
`match_options` des indizierten Suchfelds vorkommen; sonst gibt es einen Fehler.

### API: Search Fields und Cached Search (Searcher 1.4)

[Offizielle FLOW Search-API-Dokumentation](https://developers.editshare.com/?urls.primaryName=EditShare%20FLOW%20Search)


1. Der Searcher ruft `GET /fields?template=LOOKS-PROGRESS&include_filters=true` auf und
   verwendet diese Feldliste als Index. Suchfelder müssen dort vorhanden und such- oder
   filterbar sein; akzeptiert werden `fixed_field` oder der Feldname der Vorlage
   (Groß-/Kleinschreibung wird ignoriert; die Feldbezeichnung ansonsten unverändert benutzt).
   `sample.py` nutzt als Beispiel die dokumentierten Felder `MEDIA_SPACES_NAMES` und
   `CLIPNAME`. Welche Felder und Vergleichsoperatoren verfügbar sind, hängt von der
   tatsächlichen Vorlage und FLOW-Installation ab. Die Liste wird pro `link` gespeichert.
2. Über die geerbte `postThatReturnsObj("/search/cached", suchknoten)`-Methode des FLOW
   Search-Wrappers wird eine Cached Search erstellt. Dessen `createSearch` übermittelt
   keinen JSON-Suchknoten und wird daher hier nicht benutzt. Die Suche wird mit dem
   gemeinsamen Operator-Katalog und derselben Links-nach-rechts-Verknüpfung aufgebaut.
   Die Antwort liefert `cache_id` und die
   Trefferzahl `results`; **die Zahl wird sofort auf der Konsole gedruckt**.
   Die API spezifiziert `template` und `include_filters` nur für `/fields`, nicht für
   `POST /cached`. Es wird keine einfache Suche und keine Metadata-API verwendet.
3. Ergebnisse werden nur über `searchResults(cache_id, start, 100)` des FLOW
   Search-Wrappers aus `GET /cached/{cache_id}` gelesen. Die Paginierung beginnt
   mit `start=0`, `max_results=100` und setzt `start` jeweils um 100 hoch. Der Abruf
   fragt unvollständige Seiten erneut an derselben Position ab. Der mitgelieferte
   Wrapper bietet bei `searchResults` keinen `wait_for_results`-Parameter. Deshalb wird
   die Seite so lange erneut gelesen, bis alle 100 (bei der letzten Seite entsprechend
   weniger) vollständigen Datensätze vorliegen, höchstens zehn Minuten lang. Erst danach wird
   die nächste Seite gelesen. Bei dauerhaft unvollständigen Antworten gibt es einen Fehler statt
   stillschweigender Lücken. Eine Cached Search läuft serverseitig nach Inaktivität ab.
4. Die vollständigen Metadatensätze stehen unter `results[].data`. Pro Batch werden nur
   die `return_fields` für die Ergebniszeilen ausgelesen; es gibt keinen zusätzlichen
   Abruf einzelner Clips. Der Fortschritt nennt bereits abgerufene, noch abzurufende
   Ergebnisse und eine geschätzte Restzeit. Mit `on_progress` kommen die Meldungen an
   den Callback, sonst erscheinen sie auf der Konsole.

Optional nimmt `find(search, on_page=save_page)` einen Callback an. Er bekommt nach
**jeder vollständigen Seite** die extrahierten CSV-Zeilen. `sample.py` schreibt diese
sofort in eine CSV und synchronisiert sie mit dem Datenträger. Bereits geschriebene
Seiten bleiben bei späterem Fehler/Abbruch erhalten. Eine solche CSV ist **teilweise**,
nicht ein vollständiges Ergebnis. `find` gibt die Zeilen weiterhin zusätzlich in `match`
zurück; bei großen Abfragen benötigt dies entsprechend Speicher.

### Datei-Modus
Die Parquet-Datei wird blockgruppenweise gelesen. Je Blockgruppe läuft zuerst der
vektorisierte Vorfilter über die Suchspalten, anschließend die exakte zeilenweise
Prüfung der Kandidaten. Der Fortschritt nennt Blockgruppe, vorgefilterte Clips und
Kandidaten. `on_page` wird in diesem Modus nicht verwendet; die CSV-Ausgabe des Beispiels
bleibt eine einmalige Ausgabe nach erfolgreichem Abschluss.

Hier sind Feldnamen unabhängig von Groß-/Kleinschreibung: Ohne Punkt treffen sie jedes
entsprechend benannte Feld in beliebiger Tiefe; mit Punkt ist es der vollständige Pfad.
Falls dieser nicht vorkommt, wird unter `custom_metadata` auch der Name mit Unterstrich
statt Punkt geprüft (`foo.bar` → `custom_metadata.foo_bar`). Fehlende oder leere Felder
ergeben `False`, auch bei Negation. Ein unbekannter Operator ergibt `False` statt einer
Fehlermeldung. Diese lokale Logik gilt **nicht** für den API-Modus: Dort entscheidet die
Search-API über Treffer und die Semantik fehlender Felder. Der Vorfilter nutzt `is` und
`contains` auf Textspalten; sonst werden alle Zeilen als Kandidaten geprüft.

## Beispielimplementierung

```bash
python sample.py
```

`sample.py` enthält genau eine Suchliste; voreingestellt bleibt
`metadata_source = "file"` mit den bisherigen Parquet-Feldern `media_space_name` und
`userpath`. Für `metadata_source = "api"` muss der Aufrufer **die Feldnamen in
`request_fields` selbst** auf passende Einträge aus dem Search-Fields-Index ändern
(z. B. `MEDIA_SPACES_NAMES` und `CLIPNAME`) und die optionale API-Abhängigkeit
installieren. Es gibt keine automatische Feldzuordnung und keine zweite Suchliste. Treffer liegen unter
`searches/<zeitstempel>_<name>_result.csv`, Meldungen unter `searcher.log`.
Im API-Modus entsteht die CSV mit Kopfzeile vor der Suche; nach jeder Seite werden
weitere Treffer gesichert. Im Datei-Modus wird die CSV wie bisher erst zum Schluss
erzeugt. Änderungen an den Suchfeldern im API-Modus müssen mit `/fields` kompatibel sein.

## Updates in anderen Repos

```bash
pip install --force-reinstall --no-deps "searcher @ git+https://github.com/PROGRESS-MAM/ES-Search.git@main"
```
