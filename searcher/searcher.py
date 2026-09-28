# --------- IMPORTS ---------
import traceback
import json
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
from dotenv import load_dotenv
from pathlib import Path
import os
import shutil
import subprocess
import time
from datetime import timedelta
from threading import Event, Thread
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


# --------- CONFIG ---------
app_name = "Searcher"
app_version = "1.4"

share_path = Path("SMB File Exchange") / "Metadata_File"
file_name = "all_clips_all_metadata.parquet"

# Elternfeld der umbenannten Custom-Metadaten, siehe resolve_field
custom_field_parent = "custom_metadata"

# Arrow vergleicht nur nach Kleinschreibung, eval_request_item nach casefold, darum
# sind Zeilen mit solchen Zeichen im Vorfilter immer Kandidaten.
casefold_risk_pattern = "[" + "".join(
    chr(code) for code in range(0x80, 0x110000)
    if chr(code).casefold() != chr(code).lower()) + "]"


# --------- STATE ---------
link_state: Dict[str, Any] = {
    "metadata_source": None,    # "api" oder "file"
    "cred_path": None,          # vom Caller uebergeben
    "on_progress": None,        # optionaler Callback(str)
    "api": None,                # Search-API-Session
    "search_fields": None,      # Suchfelder der gewaehlten Vorlage
    "file_full_path": None,     # gemounteter File-Pfad
}


# --------- FUNC LOGIC ---------
operator_specs = {
    "is": ("EQUAL_TO", "is", False),
    "is not": ("IS_NOT_EQUAL_TO", "is", True),
    "contains": ("CONTAINS", "contains", False),
    "contains not": ("DOES_NOT_CONTAIN", "contains", True),
    "starts_with": ("BEGINS_WITH", "starts_with", False),
    "ends_with": ("ENDS_WITH", "ends_with", False),
    ">": ("GREATER_THAN", ">", False),
    "<": ("LESS_THAN", "<", False),
    ">=": ("GREATER_THAN_EQUAL_TO", ">=", False),
    "<=": ("LESS_THAN_EQUAL_TO", "<=", False),
    "not >": ("LESS_THAN_EQUAL_TO", ">", True),
    "not <": ("GREATER_THAN_EQUAL_TO", "<", True),
    "not >=": ("LESS_THAN", ">=", True),
    "not <=": ("GREATER_THAN", "<=", True),
}

bool_logic = {
    "and": lambda left, right: left and right,
    "or": lambda left, right: left or right,
}


def split_negation(operator: str):
    """Operator und Negation trennen: "is not" wird zu ("is", True)."""
    spec = operator_specs.get(operator)
    return (spec[1], spec[2]) if spec else (operator, False)


def fold_logic(parts: list, operations: dict):
    """Bedingungen und Verknüpfungen strikt von links nach rechts zusammenfassen.

    parts wechselt zwischen Bedingung und Verknüpfung: [wert, "and", wert, ...].
    """
    if not parts:
        return None

    if len(parts) % 2 == 0:
        raise ValueError("Der Suchausdruck endet mit einer Verknüpfung.")

    for index, part in enumerate(parts):
        is_operator = isinstance(part, str)
        if index % 2 == 0 and is_operator:
            raise ValueError(f"Bedingung erwartet, Verknüpfung '{part}' gefunden.")
        if index % 2 == 1 and not (is_operator and part in operations):
            raise ValueError(f"Verknüpfung 'and' oder 'or' erwartet, '{part}' gefunden.")

    accumulated = parts[0]
    for index in range(1, len(parts) - 1, 2):
        accumulated = operations[parts[index]](accumulated, parts[index + 1])

    return accumulated


# --------- FUNC PARQUET ---------
class ParquetMetadataSource:
    def __init__(self, parquet_path, fields, request_fields) -> None:
        self.parquet_file = pq.ParquetFile(str(parquet_path))
        self.request_fields = request_fields
        self.leaves = collect_leaves(self.parquet_file)
        self.resolved = {field: resolve_field(self.leaves, field) for field in fields}
        self.conditions = [item for item in request_fields if isinstance(item, tuple)]
        self.request_columns = self.columns_for([item[0] for item in self.conditions])
        self.value_columns = self.columns_for(fields)
        self.num_row_groups = self.parquet_file.num_row_groups
        self.rows_scanned = 0
        self.candidates = 0
        self.use_prefilter = True
        self.impossible = bool(self.conditions) and all(
            not self.resolved.get(item[0]) for item in self.conditions)

    def columns_for(self, field_names) -> List[str]:
        columns: List[str] = []
        for field in field_names:
            for leaf in self.resolved.get(field, []):
                if leaf["physical"] not in columns:
                    columns.append(leaf["physical"])
        return columns

    def iter_clips(self) -> Iterator[Dict[str, Any]]:
        if self.impossible:
            report_progress("Kein Feld der Suche kommt in der Datei vor, keine Treffer moeglich")
            return

        for group in range(self.num_row_groups):
            group_rows = self.parquet_file.metadata.row_group(group).num_rows
            self.rows_scanned += group_rows

            row_index = pa.array(range(group_rows), type=pa.int64())
            table = None
            mask = None

            if self.use_prefilter and self.request_columns:
                table = self.parquet_file.read_row_group(group, columns=self.request_columns)
                mask = prefilter_mask(table, self.request_fields, self.resolved,
                                      group_rows, row_index)

            indices = row_index if mask is None else pc.indices_nonzero(mask)
            self.candidates += len(indices)

            report_progress(
                f"Blockgruppe {group + 1} von {self.num_row_groups}, "
                f"{self.rows_scanned:_} Clips vorgefiltert, "
                f"{self.candidates:_} Kandidaten".replace("_", "."))

            if len(indices):
                if table is not None and self.value_columns == self.request_columns:
                    values = table
                else:
                    values = self.parquet_file.read_row_group(group, columns=self.value_columns)
                for row in values.take(indices).to_pylist():
                    yield drop_empty(row)


def collect_leaves(parquet_file) -> List[Dict[str, Any]]:
    """Alle Blattspalten der Datei mit logischem Pfad, physischem Spaltennamen,
    oberstem Feld und den Schritten dorthin."""
    logical_paths: List[List[str]] = []
    steps_per_leaf: List[list] = []

    def walk(name, arrow_type, logical, steps):
        logical = logical + [name]
        while pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
            steps = steps + [("list", None)]
            arrow_type = arrow_type.value_type
        if pa.types.is_struct(arrow_type):
            for child in arrow_type:
                walk(child.name, child.type, logical, steps + [("field", child.name)])
            return
        logical_paths.append(logical)
        steps_per_leaf.append(steps)

    for field in parquet_file.schema_arrow:
        walk(field.name, field.type, [], [])

    physical_paths = [parquet_file.schema.column(index).path
                      for index in range(len(parquet_file.schema))]

    if len(physical_paths) != len(logical_paths):
        raise RuntimeError(f"Schema passt nicht zur Datei: {len(logical_paths)} Blaetter im "
                           f"Schema, {len(physical_paths)} Spalten in der Datei")

    return [{"logical": ".".join(logical), "physical": physical,
             "top": logical[0], "steps": steps}
            for logical, physical, steps in zip(logical_paths, physical_paths, steps_per_leaf)]


def resolve_field(leaves, field: str) -> List[Dict[str, Any]]:
    """Feldname auf Blattspalten abbilden, genau wie find_all_field_values aufloest:
    ein Name mit Punkt ist der vollstaendige Pfad ab der Wurzel, ein Name ohne Punkt
    trifft jedes Blatt mit diesem Namen.
    """
    wanted = field.casefold()
    if "." in field:
        hits = [leaf for leaf in leaves if leaf["logical"].casefold() == wanted]
        if hits:
            return hits
        # Custom-Feldnamen mit Punkt stehen mit Unterstrich unter custom_metadata
        wanted = f"{custom_field_parent}.{field.replace('.', '_')}".casefold()
        return [leaf for leaf in leaves if leaf["logical"].casefold() == wanted]
    return [leaf for leaf in leaves
            if leaf["logical"].rsplit(".", 1)[-1].casefold() == wanted]


def leaf_values(table, leaf):
    """Blattwerte einer Blockgruppe flach, dazu die Zeilennummer je Wert."""
    array = single_array(table.column(leaf["top"]))
    parents = None
    for kind, name in leaf["steps"]:
        if kind == "list":
            indices = pc.list_parent_indices(array)
            array = pc.list_flatten(array)
            parents = indices if parents is None else pc.take(parents, indices)
        else:
            array = pc.struct_field(array, [name])
    return array, parents


def single_array(column):
    chunks = column.chunks
    if len(chunks) == 1:
        return chunks[0]
    if not chunks:
        return pa.array([], type=column.type)
    return pa.concat_arrays(chunks)


def rows_of_matches(values_mask, parents, row_index):
    filled = pc.fill_null(values_mask, False)
    if parents is None:
        return filled
    return pc.is_in(row_index, value_set=pc.cast(pc.filter(parents, filled), pa.int64()))


def prefilter_item(table, leaves, operator, request_value, num_rows, row_index):
    """Vektorisierter Vorfilter fuer eine Bedingung.

    Rueckgabe None heisst: alle Zeilen sind Kandidaten. Der Vorfilter darf zu weit
    sein, aber nie zu eng - entschieden wird ausschliesslich in eval_requests.
    """
    if not leaves:
        return pa.array([False] * num_rows)

    operator, negated = split_negation(operator)
    if negated or operator not in ("is", "contains", "starts_with", "ends_with"):
        return None

    if isinstance(request_value, (list, tuple)):
        needles = [str(item).casefold() for item in request_value]
    else:
        needles = [str(request_value).casefold()]

    mask = None
    for leaf in leaves:
        array, parents = leaf_values(table, leaf)
        if not (pa.types.is_string(array.type) or pa.types.is_large_string(array.type)):
            return None
        found = pc.match_substring_regex(array, casefold_risk_pattern)
        for needle in needles:
            found = pc.or_(found, pc.match_substring(array, needle, ignore_case=True))
        rows = rows_of_matches(found, parents, row_index)
        mask = rows if mask is None else pc.or_(mask, rows)
    return mask


def prefilter_mask(table, request_fields, resolved, num_rows, row_index):
    """Kandidatenmaske einer Blockgruppe, in derselben Reihenfolge wie eval_requests."""

    def mask_and(left, right):
        if left is None:
            return right
        if right is None:
            return left
        return pc.and_(left, right)

    def mask_or(left, right):
        if left is None or right is None:
            return None
        return pc.or_(left, right)

    mask_logic = {"and": mask_and, "or": mask_or}

    parts = []
    for item in request_fields:
        if isinstance(item, tuple):
            field, operator, request_value = item
            parts.append(prefilter_item(table, resolved.get(field, []), operator,
                                        request_value, num_rows, row_index))
        elif isinstance(item, str):
            parts.append(item)

    return fold_logic(parts, mask_logic)


def drop_empty(value):
    """Leere Werte entfernen, damit fehlende Felder als nicht vorhanden gelten."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = drop_empty(item)
            if item not in (None, "", [], {}):
                cleaned[key] = item
        return cleaned
    if isinstance(value, list):
        cleaned = []
        for item in value:
            item = drop_empty(item)
            if item not in (None, "", [], {}):
                cleaned.append(item)
        return cleaned
    return value


# --------- FUNC SEARCH ---------
def report_progress(message: str) -> None:
    callback = link_state.get("on_progress")
    if callable(callback):
        callback(message)


def mount_share() -> Path:
    cred_path = link_state.get("cred_path")
    if not cred_path:
        raise RuntimeError("Kein cred_path gesetzt, bitte searcher.link(...) aufrufen.")
    if not Path(cred_path).is_file():
        raise FileNotFoundError(f"cred.env nicht gefunden: '{cred_path}'")

    load_dotenv(cred_path, override=True)
    host = os.environ.get("SMB_HOST")
    user = os.environ.get("SMB_USER")
    password = os.environ.get("SMB_PASSWORD")

    if not host:
        raise RuntimeError(f"SMB_HOST fehlt in '{cred_path}'.")

    full_path = Path("\\\\" + "\\".join((host, *share_path.parts, file_name)))

    if user:
        share = f"\\\\{host}\\IPC$"
        command = ["net", "use", share, password, f"/user:{user}", "/persistent:no"]
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"net use fehlgeschlagen: {result.stdout} {result.stderr}")

    return full_path


def find_all_field_values(metadata: Any, field: str) -> List[Any]:
    seen = set()
    results = []

    def norm(v: Any) -> str:
        if isinstance(v, (dict, list, tuple)):
            return json.dumps(v, sort_keys=True, ensure_ascii=False)
        if isinstance(v, str):
            return v.casefold()
        return str(v)

    def collect(value: Any):
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        key = norm(value)
        if key not in seen:
            seen.add(key)
            results.append(value)

    def recurse(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.casefold() == field.casefold():
                    collect(v)
                recurse(v)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                recurse(item)

    def walk(obj: Any, segments: tuple):
        if not segments:
            collect(obj)
            return
        head, rest = segments[0], segments[1:]
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.casefold() == head.casefold():
                    walk(v, rest)
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                walk(item, segments)

    if "." in field:
        if isinstance(metadata, dict) and field in metadata:
            collect(metadata[field])                    # Pfad direkt vorhanden
        else:
            walk(metadata, tuple(field.split(".")))     # verschachtelte Struktur
        if not results:
            # Custom-Feldnamen mit Punkt stehen mit Unterstrich unter custom_metadata
            walk(metadata, (custom_field_parent, field.replace(".", "_")))
    else:
        recurse(metadata)

    return results


def eval_request_item(metadata: dict, request_item: tuple) -> bool:
    request_field, request_operator, request_value = request_item
    request_operator, negated = split_negation(request_operator)
    actual_values = find_all_field_values(metadata, request_field)

    if not actual_values:
        return False

    result = matches_operator(actual_values, request_operator, request_value)
    return not result if negated else result


def matches_operator(actual_values: list, request_operator: str, request_value: Any) -> bool:
    """Prueft, ob einer der gefundenen Werte zum Operator passt."""
    if request_operator == "is":
        for value in actual_values:
            if str(value).casefold() == str(request_value).casefold():
                return True
        return False

    if request_operator in ("contains", "starts_with", "ends_with"):
        request_values = request_value if isinstance(request_value, (list, tuple)) else (request_value,)
        compare = {
            "contains": lambda actual, sought: sought in actual,
            "starts_with": str.startswith,
            "ends_with": str.endswith,
        }[request_operator]
        return any(compare(str(actual).casefold(), str(sought).casefold())
                   for actual in actual_values for sought in request_values)

    if request_operator in (">", "<", ">=", "<="):
        value_num = float(request_value)

        for value in actual_values:
            try:
                actual_num = float(value)
            except Exception:
                continue

            if request_operator == ">" and actual_num > value_num:
                return True
            if request_operator == "<" and actual_num < value_num:
                return True
            if request_operator == ">=" and actual_num >= value_num:
                return True
            if request_operator == "<=" and actual_num <= value_num:
                return True

        return False

    return False


def eval_requests(metadata: dict, requests: tuple) -> bool:
    parts = []

    for item in requests:
        if isinstance(item, tuple):
            parts.append(eval_request_item(metadata, item))
        elif isinstance(item, str):
            parts.append(item)

    if not parts:
        return False

    return bool(fold_logic(parts, bool_logic))


# --------- FUNC API SEARCH ---------
search_template = "LOOKS-PROGRESS"
page_size = 100


def _api_response(action, callback, status=None):
    if status is not None:
        stopped = Event()
        started = time.monotonic()
        _api_progress(status(0))

        def heartbeat():
            while not stopped.wait(2):
                _api_progress(status(int(time.monotonic() - started)))

        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
    try:
        result = callback()
    finally:
        if status is not None:
            stopped.set()
            thread.join()
    code = link_state["api"].last_return_code()
    if code != 200:
        raise RuntimeError(f"Search-API: {action} fehlgeschlagen (HTTP {code}).")
    return result


def _field_key(name):
    return name.casefold()


def _search_fields():
    fields = link_state.get("search_fields")
    if fields is None:
        api = link_state["api"]
        fields = _api_response("Search Fields", lambda: api.getThatReturnsObj(
            f"/search/fields?template={search_template}&include_filters=true"),
            status=lambda elapsed: f"Suchfelder werden geladen, warte seit {elapsed} s")
        if not isinstance(fields, list):
            raise ValueError("Search Fields liefert keine Feldliste.")
        link_state["search_fields"] = fields
    return fields


def _resolve_search_field(name, operator):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Ein Suchfeld muss als Feldname angegeben sein.")
    key = _field_key(name)
    candidates = [field for field in _search_fields() if isinstance(field, dict) and
                  any(_field_key(alias) == key for alias in
                      (field.get("fixed_field"), field.get("custom_field"), field.get("name"))
                      if isinstance(alias, str))]
    if not candidates:
        raise ValueError(f"Suchfeld '{name}' fehlt im Search-Fields-Index der Vorlage {search_template}.")
    if len(candidates) != 1:
        raise ValueError(f"Suchfeld '{name}' ist mehrdeutig; bitte fixed_field verwenden.")
    field = candidates[0]
    if not (field.get("can_search") or field.get("can_filter")):
        raise ValueError(f"Suchfeld '{name}' ist weder suchbar noch filterbar.")
    spec = operator_specs.get(operator)
    if not spec or spec[0] not in field.get("match_options", []):
        raise ValueError(f"Operator '{operator}' ist fuer Suchfeld '{name}' nicht verfuegbar; erlaubt: {field.get('match_options', [])}.")
    return (field.get("name") if field.get("custom_field") else field.get("fixed_field") or field.get("name")), spec[0]


def _search_node(request_fields):
    if not isinstance(request_fields, (tuple, list)) or not request_fields:
        raise ValueError("request_fields muss mindestens eine Bedingung enthalten.")

    def condition(item):
        if not isinstance(item, tuple) or len(item) != 3:
            raise ValueError("Bedingung muss (feld, operator, wert) sein.")
        name, operator, value = item
        field, match = _resolve_search_field(name, operator)
        values = value if operator == "contains" and isinstance(value, (list, tuple)) else (value,)
        if not values or any(not isinstance(entry, (str, int, float)) or isinstance(entry, bool)
                             for entry in values):
            raise ValueError("Search-API-Suchwerte muessen Text oder Zahlen sein; 'contains'-Listen duerfen nicht leer sein.")
        filters = [{"field": field, "match": match, "search": entry} for entry in values]
        return {"combine": "MATCH_ANY" if len(filters) > 1 else "MATCH_ALL", "filters": filters}

    parts = [condition(part) if isinstance(part, tuple) else part for part in request_fields]
    combine = {key: lambda left, right, op=value: {"combine": op, "children": [left, right]}
               for key, value in (("and", "MATCH_ALL"), ("or", "MATCH_ANY"))}
    return fold_logic(parts, combine)


def _api_progress(message):
    if callable(link_state.get("on_progress")):
        report_progress(message)
    else:
        print(message, flush=True)


def _cached_progress(checked, total, page, started, detail=""):
    ratio = checked / total if total else 1
    eta = (str(timedelta(seconds=round((time.monotonic() - started) / checked * (total - checked))))
           if checked and checked < total else "--:--:--" if total and not checked else "0:00:00")
    pages = (total + page_size - 1) // page_size
    prefix = "Cached ["
    suffix = f"] {ratio:.0%} | Clips {checked}/{total} | Seite {page} von {pages} | Restzeit {eta}"
    extra = f" | {detail}" if detail else ""
    width = max(4, min(18, shutil.get_terminal_size((100, 24)).columns - 1
                       - len(prefix) - len(suffix) - len(extra)))
    filled = round(width * ratio)
    return f"{prefix}{'#' * filled}{'-' * (width - filled)}{suffix}{extra}"


def _cached_page(cache_id, start, total, started):
    api = link_state["api"]
    expected = min(page_size, total - start)
    page_number = start // page_size + 1
    deadline = time.monotonic() + 600
    while True:
        page = _api_response(f"Ergebnisse ab {start}",
                             lambda: api.searchResults(cache_id, start, page_size),
                             status=lambda elapsed: _cached_progress(
                                 start, total, page_number, started, f"lade {elapsed}s"))
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise ValueError(f"Cached Search liefert keine Ergebnisseite ab Position {start}.")
        if page.get("total") != total or page.get("start") != start:
            raise ValueError(f"Cached Search meldet ab Position {start} eine abweichende Gesamtzahl oder Startposition.")
        results = page["results"]
        if len(results) == expected and all(isinstance(item, dict) and
                                             isinstance(item.get("data"), dict) for item in results):
            return [item["data"] for item in results]
        if len(results) > expected or page.get("complete") is True:
            raise ValueError(f"Cached Search liefert ab Position {start} keine {expected} vollstaendigen Datensaetze.")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Cached Search ab Position {start} nicht vollstaendig aufgeloest; bisherigen CSV-Stand behalten.")
        _api_progress(_cached_progress(start, total, page_number, started, "Seite wird aufgeloest"))
        time.sleep(1)


def _api_batches(search):
    node = _search_node(search["request_fields"])
    api = link_state["api"]
    created = _api_response("Cached Search erstellen", lambda: api.postThatReturnsObj("/search/cached", node),
                            status=lambda elapsed: f"Cached Search wird erstellt, warte seit {elapsed} s")
    if not isinstance(created, dict) or not isinstance(created.get("cache_id"), str):
        raise ValueError("Cached Search liefert keine Search-ID.")
    total = created.get("results")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("Cached Search liefert keine gueltige Trefferzahl.")
    cache_id = created["cache_id"]
    _api_progress(f"Cached Search: {total} Ergebnisse (Search-ID {cache_id})")
    started = time.monotonic()
    _api_progress(_cached_progress(0, total, 0, started))
    for start in range(0, total, page_size):
        yield _cached_page(cache_id, start, total, started), total, started


def _result_row(metadata, fields):
    return ["; ".join(str(value) for value in find_all_field_values(metadata, field))
            for field in fields]


# --------- MAIN ---------
def link(metadata_source: str = "file", cred_path: Union[str, Path] = None,
         on_progress: Optional[Callable[[str], None]] = None,
         api_link: Optional[Callable[[], Any]] = None) -> None:
    """Verbindet 'file' mit dem Share oder 'api' ueber TOOLBOX mit FLOW Search."""
    if metadata_source not in ("api", "file"):
        raise ValueError(f"Unbekannte Datenquelle '{metadata_source}', erlaubt: 'api', 'file'.")

    link_state["metadata_source"] = metadata_source
    link_state["cred_path"] = Path(cred_path) if cred_path else None
    link_state["on_progress"] = on_progress
    link_state["api"] = None
    link_state["search_fields"] = None
    link_state["file_full_path"] = None
    report_progress(f"Datenquelle '{metadata_source}' wird verbunden")

    if metadata_source == "file":
        link_state["file_full_path"] = mount_share()
        return
    if not link_state["cred_path"] or not link_state["cred_path"].is_file():
        raise FileNotFoundError("Fuer 'api' wird eine vorhandene cred.env mit FLOW_HOST, FLOW_USER und FLOW_PASSWORD benoetigt.")
    if api_link is None:
        from toolbox import tb_link_api
        api_link = lambda: tb_link_api(link_state["cred_path"], "search")
    if not callable(api_link):
        raise ValueError("api_link muss eine aufrufbare Funktion sein.")
    api = api_link()
    if api is None:
        raise RuntimeError("TOOLBOX konnte keine FLOW Search-API verbinden; Zugangsdaten und Installation pruefen.")
    link_state["api"] = api


def find(search: dict = None, on_page: Optional[Callable[[List[List[str]]], None]] = None) -> Tuple[List[List[str]], str, Optional[str]]:
    """Durchsucht die Quelle; on_page erhaelt vollstaendige API-Seiten als Ergebniszeilen.

    Rueckgabe: (Trefferzeilen, Abschlussstatus, Fehlertext oder None).
    """
    matches: List[List[str]] = []
    progress = ""
    try:
        mode = link_state.get("metadata_source")
        if mode not in ("api", "file"):
            raise RuntimeError("Keine Datenquelle verlinkt, bitte searcher.link(...) aufrufen.")
        if not isinstance(search, dict) or not search:
            raise ValueError("Keine Suche uebergeben.")
        request_fields = search["request_fields"]
        fields = search.get("return_fields", ())
        if not isinstance(fields, (list, tuple)) or any(not isinstance(field, str) for field in fields):
            raise ValueError("return_fields muss eine Liste von Feldnamen sein.")

        source = None
        if mode == "file":
            names = tuple(dict.fromkeys(
                [item[0] for item in request_fields if isinstance(item, tuple)] + list(fields)))
            source = ParquetMetadataSource(link_state["file_full_path"], names, request_fields)
            batches = (([row], None, None) for row in source.iter_clips())
        else:
            batches = _api_batches(search)

        checked = 0
        start_message = f"Suche '{search.get('name', '')}' gestartet"
        (_api_progress if mode == "api" else report_progress)(start_message)
        for batch, total, started in batches:
            rows = [_result_row(row, fields) for row in batch
                    if mode == "api" or eval_requests(row, request_fields)]
            if mode == "api" and on_page is not None:
                on_page(rows)
            matches.extend(rows)
            checked += len(batch)
            if mode == "api":
                page_number = (checked + page_size - 1) // page_size
                _api_progress(_cached_progress(checked, total, page_number, started))

        if source is not None:
            checked = source.rows_scanned
        progress = (f"Suche '{search.get('name', '')}' beendet, {checked:_} Clips geprueft, "
                    f"{len(matches):_} Treffer gefunden.").replace("_", ".") if mode == "file" else (
                    f"Suche '{search.get('name', '')}' beendet, {checked} Ergebnisse abgerufen, {len(matches)} Treffer gefunden.")
        if mode == "api":
            _api_progress(progress)
        else:
            report_progress(progress)
        return matches, progress, None
    except Exception as exc:
        return matches, progress, f"Unhandled error in searcher: {exc}\n{traceback.format_exc()}"
