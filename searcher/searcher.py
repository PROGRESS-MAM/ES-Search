# --------- IMPORTS ---------
from toolbox import tb_link_api, tb_write_log, tb_make_path
import traceback
import json
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union
import datetime
import csv
from dotenv import load_dotenv
from pathlib import Path
import os
import subprocess


# --------- STATIC ---------
app_name = "Searcher"
app_version = "0.6"
main_log = Path(__file__).parent / "searcher.log"

csv_path = Path("SMB File Exchange") / "CSV"
csv_file = "all_clips_all_metadata.csv"


# --------- STATE ---------
link_state: Dict[str, Any] = {
    "metadata_source": None,    # "api" oder "csv"
    "cred_path": None,          # vom Caller uebergeben
    "offset": 0,                # Zahl oder False
    "limit": False,             # Zahl oder False (False = alles)
    "on_progress": None,        # optionaler Callback(str)
    "api": None,                # verbundene API-Instanz
    "csv_full_path": None,      # gemounteter CSV-Pfad
}


# --------- CLASS ---------
class CsvMetadataSource:
    ENCODING = "utf-8-sig"
    DELIMITER = ","
    BUFFER = 4 * 1024 * 1024

    def __init__(self, csv_path, fields) -> None:
        self.csv_path = str(csv_path)
        with self._open() as csvfile:
            header = next(csv.reader(csvfile, delimiter=self.DELIMITER))
        self.columns = {
            field: [index for index, name in enumerate(header)
                    if name.casefold() == field.casefold()
                    or ("." not in field and name.rsplit(".", 1)[-1].casefold() == field.casefold())]
            for field in fields
        }

    def _open(self):
        return open(self.csv_path, "r", newline="", encoding=self.ENCODING, buffering=self.BUFFER)

    def iter_clips(self, offset: int = 0, limit: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        with self._open() as csvfile:
            reader = csv.reader(csvfile, delimiter=self.DELIMITER)
            next(reader)
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                if limit is not None and index >= offset + limit:
                    return
                yield {field: [row[i] for i in columns if row[i]]
                       for field, columns in self.columns.items()}


# --------- FUNC ---------
def normalize_range(value: Union[int, bool, None], default: Optional[int]) -> Optional[int]:
    if value is False or value is None:
        return default
    return int(value)


def report_progress(message: str) -> None:
    callback = link_state.get("on_progress")
    if callable(callback):
        callback(message)


def mount_csv_share() -> Path:
    cred_path = link_state.get("cred_path")
    if not cred_path:
        raise RuntimeError("Kein cred_path gesetzt, bitte searcher.link(...) aufrufen.")

    load_dotenv(cred_path, override=True)
    host = os.environ.get("CSV_HOST")
    user = os.environ.get("CSV_USER")
    password = os.environ.get("CSV_PASSWORD")

    if not all((host, user, password)):
        raise RuntimeError(f"CSV_HOST, CSV_USER, CSV_PASSWORD fehlt in '{cred_path}'.")


    full_path = Path("\\\\" + "\\".join((host, *csv_path.parts, csv_file)))

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
            collect(metadata[field])                    # flache CSV-Zeile
        else:
            walk(metadata, tuple(field.split(".")))     # verschachtelte API-Daten
    else:
        recurse(metadata)

    return results


def eval_request_item(metadata: dict, request_item: tuple) -> bool:
    request_field, request_operator, request_value = request_item
    actual_values = find_all_field_values(metadata, request_field)

    if not actual_values:
        return False

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
def link(metadata_source: str, cred_path: Union[str, Path], offset: Union[int, bool], limit: Union[int, bool], on_progress: Optional[Callable[[str], None]]) -> None:
    link_state["metadata_source"] = metadata_source
    link_state["cred_path"] = Path(cred_path) if cred_path else None
    link_state["offset"] = offset
    link_state["limit"] = limit
    link_state["on_progress"] = on_progress
    link_state["api"] = None
    link_state["csv_full_path"] = None

    report_progress(f"Datenquelle '{metadata_source}' wird verbunden")

    if metadata_source == "api":
        link_state["api"] = tb_link_api(cred_path, "metadata")
    else:
        link_state["csv_full_path"] = mount_csv_share()


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

        if metadata_source == "api":
            api = link_state["api"]
            api_limit = limit_value if limit_value is not None else api.numClips()
            clip_ids = api.clips(offset=offset_value, limit=api_limit)
            clip_stream = (api.getClip(clip_id) for clip_id in clip_ids)
            total = len(clip_ids)
            step = 1

        else:
            csv_source = CsvMetadataSource(link_state["csv_full_path"], fields)
            clip_stream = csv_source.iter_clips(offset=offset_value, limit=limit_value)
            total = limit_value
            step = 1000

        clip_index = 0
        report_progress(f"Suche '{search.get('name', '')}' gestartet")

        for clip_index, clip_all_metadata in enumerate(clip_stream, start=1):
            if clip_index == 1 or clip_index % step == 0:
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

        progress = (f"Suche '{search.get('name', '')}' beendet, {clip_index:_} Clips geprueft, "
                    f"{len(matches):_} Treffer gefunden.").replace("_", ".")
        report_progress(progress)

        return matches, progress, None

    except Exception as exc:
        error = f"Unhandled error in searcher: {exc}\n{traceback.format_exc()}"
        return matches, progress, error







# --------- CONFIG ---------
metadata_source = "csv"     # "api"
cred_path = Path(__file__).parent / "cred.env"
offset = 0
limit = False

# --------- SEARCHES ---------
searches = [
    {
        "name": "LTO Content",
        "request_fields": (
            ("display_backups", "is", "LS1901L7"),
        ),
        "return_fields": ("clip_id", "media_space_name", "display_name", "hash", "userpath", "display_backups"),
    }
]

# --------- EXEC ---------
if __name__ == "__main__":
    tb_write_log(main_log, f"{app_name} {app_version} started.")

    def print_progress(message: str) -> None:
        print(f"\r{message:<60}", end="", flush=True)

    link(metadata_source, cred_path, offset=offset, limit=limit, on_progress=print_progress)

    for search in searches:
        match, progress, error = find(search)
        print()

        if error:
            print(error)
            tb_write_log(main_log, error)
            continue

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        result_csv = tb_make_path(Path(__file__).parent, "searches", search["name"], f"result_{timestamp}.csv")

        with open(result_csv, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(search["return_fields"])
            writer.writerows(match)

        print(progress)
        tb_write_log(main_log, progress)