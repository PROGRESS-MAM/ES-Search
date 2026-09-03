# --------- IMPORTS ---------
import traceback
import json
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
from dotenv import load_dotenv
from pathlib import Path
import os
import subprocess
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


# --------- STATIC ---------
app_name = "Searcher"
app_version = "1.0"

share_path = Path("SMB File Exchange") / "Metadata_File"
metadata_file = "all_clips_all_metadata.parquet"


#besser:
'''
. Gefaltet schreiben statt zur Laufzeit falten — der eigentlich leichte Weg. Im Dumper pro Zeile alle String-Blätter
casefold()-en und mit \n zu einer Suchspalte verketten. Der Vorfilter ist dann ein einziges pc.match_substring(blob, needle) ohne ignore_case,
ohne Risikoliste, ohne Leaf-Walk — und semantisch identisch zu eval_requests. Für feldbezogene Bedingungen ist er breiter
 (Treffer könnte aus einem anderen Feld kommen), das ist erlaubt, solange nur eine Übermenge entsteht. Kostet Speicherplatz und einen Re-Dump.


# Arrow vergleicht nur nach Kleinschreibung, eval_request_item nach casefold. Bei diesen
# Zeichen fallen beide auseinander ("strasse" trifft "Straße" nur per casefold), darum
# sind Zeilen mit solchen Zeichen im Vorfilter immer Kandidaten.
casefold_risk_ranges = (
    "00b5", "00df", "0149", "017f", "01f0", "0345", "0390", "03b0", "03c2",
    "03d0-03d1", "03d5-03d6", "03f0-03f1", "03f5", "0587", "13a0-13f5",
    "13f8-13fd", "1c80-1c88", "1e96-1e9b", "1e9e", "1f50", "1f52", "1f54",
    "1f56", "1f80-1faf", "1fb2-1fb4", "1fb6-1fb7", "1fbc", "1fbe",
    "1fc2-1fc4", "1fc6-1fc7", "1fcc", "1fd2-1fd3", "1fd6-1fd7", "1fe2-1fe4",
    "1fe6-1fe7", "1ff2-1ff4", "1ff6-1ff7", "1ffc", "ab70-abbf", "fb00-fb06",
    "fb13-fb17",
)

casefold_risk_pattern = "[" + "".join(
    "-".join(chr(int(code, 16)) for code in item.split("-"))
    for item in casefold_risk_ranges) + "]"

'''
    

# --------- STATE ---------
link_state: Dict[str, Any] = {
    "metadata_source": None,    # "api" oder "file"
    "cred_path": None,          # vom Caller uebergeben
    "api_link": None,           # Callable des Callers, liefert die API-Instanz
    "offset": 0,                # Zahl oder False
    "limit": False,             # Zahl oder False (= alle Clips / Rows)
    "on_progress": None,        # optionaler Callback(str)
    "api": None,                # verbundene API-Instanz
    "file_full_path": None,     # gemounteter File-Pfad
}


# --------- FUNC PARQUET ---------
def collect_leaves(metadata_file) -> List[Dict[str, Any]]:
    """Alle Blattspalten mit logischem und physischem Pfad.

    logical ist der Pfad ohne die technischen Listenebenen (audio.file.file.hash).
    physical kommt aus der Datei selbst, damit die Spaltenauswahl unabhaengig davon
    stimmt, wie der Schreiber die Listenebenen benannt hat (list.element oder list.item).
    """
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

    for field in metadata_file.schema_arrow:
        walk(field.name, field.type, [], [])

    physical_paths = [metadata_file.schema.column(index).path
                      for index in range(len(metadata_file.schema))]

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
        return [leaf for leaf in leaves if leaf["logical"].casefold() == wanted]
    return [leaf for leaf in leaves
            if leaf["logical"].rsplit(".", 1)[-1].casefold() == wanted]


def single_array(column):
    chunks = column.chunks
    if len(chunks) == 1:
        return chunks[0]
    if not chunks:
        return pa.array([], type=column.type)
    return pa.concat_arrays(chunks)


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
    if operator not in ("is", "contains"):
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
        found = pc.match_substring_regex(array, casefold_risk_pattern)  ## to be changed
        for needle in needles:
            found = pc.or_(found, pc.match_substring(array, needle, ignore_case=True))
        rows = rows_of_matches(found, parents, row_index)
        mask = rows if mask is None else pc.or_(mask, rows)
    return mask


def combine_masks(left, right, operator):
    if operator == "and":
        if left is None:
            return right
        if right is None:
            return left
        return pc.and_(left, right)
    if operator == "or":
        if left is None or right is None:
            return None
        return pc.or_(left, right)
    return left


def prefilter_mask(table, request_fields, resolved, num_rows, row_index):
    """Kandidatenmaske einer Blockgruppe, in derselben Reihenfolge wie eval_requests."""
    parts = []
    for item in request_fields:
        if isinstance(item, tuple):
            field, operator, request_value = item
            parts.append(prefilter_item(table, resolved.get(field, []), operator,
                                        request_value, num_rows, row_index))
        elif isinstance(item, str):
            parts.append(item)

    if not parts:
        return None

    mask = None if isinstance(parts[0], str) else parts[0]
    index = 1
    while index < len(parts):
        operator = parts[index]
        following = parts[index + 1] if index + 1 < len(parts) else None
        if isinstance(following, str):
            following = None
        mask = combine_masks(mask, following, operator)
        index += 2

    return mask


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


class ParquetMetadataSource:
    def __init__(self, parquet_path, fields, request_fields) -> None:
        self.file = pq.ParquetFile(str(parquet_path))
        self.request_fields = request_fields
        self.leaves = collect_leaves(self.file)
        self.resolved = {field: resolve_field(self.leaves, field) for field in fields}
        self.conditions = [item for item in request_fields if isinstance(item, tuple)]
        self.request_columns = self.columns_for([item[0] for item in self.conditions])
        self.value_columns = self.columns_for(fields)
        self.num_rows = self.file.metadata.num_rows
        self.num_row_groups = self.file.num_row_groups
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

    def iter_clips(self, offset: int = 0, limit: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        if self.impossible:
            report_progress("Kein Feld der Suche kommt in der Datei vor, keine Treffer moeglich")
            return

        stop = self.num_rows if limit is None else min(self.num_rows, offset + limit)
        first_row = 0

        for group in range(self.num_row_groups):
            group_rows = self.file.metadata.row_group(group).num_rows
            last_row = first_row + group_rows

            if last_row <= offset or first_row >= stop:
                first_row = last_row
                continue

            lower = max(0, offset - first_row)
            upper = min(group_rows, stop - first_row)
            self.rows_scanned += upper - lower

            row_index = pa.array(range(group_rows), type=pa.int64())
            table = None
            mask = None

            if self.use_prefilter and self.request_columns:
                table = self.file.read_row_group(group, columns=self.request_columns)
                mask = prefilter_mask(table, self.request_fields, self.resolved,
                                      group_rows, row_index)

            if lower > 0 or upper < group_rows:
                in_range = pa.array([lower <= row < upper for row in range(group_rows)])
                mask = in_range if mask is None else pc.and_(mask, in_range)

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
                    values = self.file.read_row_group(group, columns=self.value_columns)
                for row in values.take(indices).to_pylist():
                    yield drop_empty(row)

            first_row = last_row


# --------- FUNC SEARCH ---------
def normalize_range(value: Union[int, bool, None], default: Optional[int]) -> Optional[int]:
    if value is False or value is None:
        return default
    return int(value)


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
    host = os.environ.get("CSV_HOST")
    user = os.environ.get("CSV_USER")
    password = os.environ.get("CSV_PASSWORD")

    if not host:
        raise RuntimeError(f"CSV_HOST fehlt in '{cred_path}'.")

    full_path = Path("\\\\" + "\\".join((host, *share_path.parts, metadata_file)))

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
    else:
        recurse(metadata)

    return results


def eval_request_item(metadata: dict, request_item: tuple) -> bool:
    request_field, request_operator, request_value = request_item
    actual_values = find_all_field_values(metadata, request_field)

    if not actual_values:
        return False

# logik für not -> return rumdrehen?

    if request_operator == "is":
        for value in actual_values:
            if str(value).casefold() == str(request_value).casefold():
                return True
        return False

    if request_operator == "contains":
        if isinstance(request_value, (list, tuple)):
            request_values = request_value
        else:
            request_values = (request_value,)

        for act_value in actual_values:
            for req_value in request_values:
                if str(req_value).casefold() in str(act_value).casefold():
                    return True
        return False

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
    result = []

    for item in requests:
        if isinstance(item, tuple):
            result.append(eval_request_item(metadata, item))
        elif isinstance(item, str):
            result.append(item)

    if not result:
        return False

    acc = result[0]
    index = 1
    while index < len(result):
        operator = result[index]
        next_result = result[index + 1] if index + 1 < len(result) else False

        if operator == "and":
            acc = acc and next_result
        elif operator == "or":
            acc = acc or next_result

        index += 2

    return acc


# --------- MAIN ---------
def link(metadata_source: str = "file", cred_path: Union[str, Path] = None,
         offset: Union[int, bool] = 0, limit: Union[int, bool] = False,
         on_progress: Optional[Callable[[str], None]] = None,
         api_link: Optional[Callable[[], Any]] = None) -> None:

    """Verbindet die Datenquelle. Den Pfad kennt das Modul selbst,
    offset / limit sind eine Zahl oder False (= alles).
    Fuer metadata_source 'api' liefert der Caller api_link mit z.B.
    lambda: tb_link_api(cred_path, 'metadata')."""

    if metadata_source not in ("api", "file"):
        raise ValueError(f"Unbekannte Datenquelle '{metadata_source}', erlaubt: 'api', 'file'.")

    link_state["metadata_source"] = metadata_source
    link_state["cred_path"] = Path(cred_path) if cred_path else None
    link_state["api_link"] = api_link
    link_state["offset"] = offset
    link_state["limit"] = limit
    link_state["on_progress"] = on_progress
    link_state["api"] = None
    link_state["file_full_path"] = None

    report_progress(f"Datenquelle '{metadata_source}' wird verbunden")

    if metadata_source == "api":
        if not callable(api_link):
            raise ValueError("Fuer die Datenquelle 'api' wird api_link benoetigt, "
                             "z.B. api_link=lambda: tb_link_api(cred_path, 'metadata').")
        link_state["api"] = api_link()
    else:
        link_state["file_full_path"] = mount_share()


def find(search: dict = None, offset: Union[int, bool, None] = None,
         limit: Union[int, bool, None] = None) -> Tuple[List[List[str]], str, Optional[str]]:
    """Durchsucht die verlinkte Datenquelle.
    Rueckgabe: match (Liste der Ergebniszeilen), progress (Statustext), error (Text oder None)."""
    matches: List[List[str]] = []
    progress = ""

    try:
        metadata_source = link_state.get("metadata_source")
        if not metadata_source:
            raise RuntimeError("Keine Datenquelle verlinkt, bitte searcher.link(...) aufrufen.")
        if not search:
            raise ValueError("Keine Suche uebergeben.")

        offset_value = normalize_range(offset if offset is not None else link_state["offset"], 0)
        limit_value = normalize_range(limit if limit is not None else link_state["limit"], None)

        fields = tuple(dict.fromkeys(
            [item[0] for item in search["request_fields"] if isinstance(item, tuple)]
            + list(search.get("return_fields", []))
        ))

        source = None

        if metadata_source == "api":
            api = link_state["api"]
            api_limit = limit_value if limit_value is not None else api.numClips()
            clip_ids = api.clips(offset=offset_value, limit=api_limit)
            clip_stream = (api.getClip(clip_id) for clip_id in clip_ids)
            total = len(clip_ids)
            step = 1

        else:
            source = ParquetMetadataSource(link_state["file_full_path"], fields,
                                           search["request_fields"])
            clip_stream = source.iter_clips(offset=offset_value, limit=limit_value)
            total = None
            step = 0

        clip_index = 0
        report_progress(f"Suche '{search.get('name', '')}' gestartet")

        for clip_index, clip_all_metadata in enumerate(clip_stream, start=1):
            if step and (clip_index == 1 or clip_index % step == 0):
                if total:
                    message = f"Clip {clip_index:_} von {total:_}, {len(matches):_} Treffer".replace("_", ".")
                else:
                    message = f"Clip {clip_index:_} wird durchsucht, {len(matches):_} Treffer".replace("_", ".")
                report_progress(message)

            if eval_requests(clip_all_metadata, search["request_fields"]):
                return_row = []
                for field in search.get("return_fields", []):
                    return_values = find_all_field_values(clip_all_metadata, field)
                    return_row.append("; ".join(str(value) for value in return_values))
                matches.append(return_row)

        checked = source.rows_scanned if source is not None else clip_index

        progress = (f"Suche '{search.get('name', '')}' beendet, {checked:_} Clips geprueft, "
                    f"{len(matches):_} Treffer gefunden.").replace("_", ".")
        report_progress(progress)

        return matches, progress, None

    except Exception as exc:
        error = f"Unhandled error in searcher: {exc}\n{traceback.format_exc()}"
        return matches, progress, error
