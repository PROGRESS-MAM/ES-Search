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
def link_csv_file(cred_path, fields) -> CsvMetadataSource:
    load_dotenv(cred_path, override=True)
    host = os.environ.get("CSV_HOST")
    user = os.environ.get("CSV_USER")
    password = os.environ.get("CSV_PASSWORD")

    full_path = Path("\\\\" + "\\".join((host, *csv_path.parts, csv_file)))

    if user:
        share = f"\\\\{host}\\IPC$"
        command = ["net", "use", share, password, f"/user:{user}", "/persistent:no"]
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"net use fehlgeschlagen: {result.stdout} {result.stderr}")

    return CsvMetadataSource(full_path, fields)

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
def searcher(cred_path: Path, datasource: str = None, search: dict = None, mode: str = None) -> Iterator[Dict[str, object]]:
    try:
        mode_parts = mode.split()
        if mode_parts[0] == "real":
            test_mode = False
            offset = 0
        else:
            test_mode = True
            offset = int(mode_parts[1])
            test_mode_limit = int(mode_parts[2])

        fields = tuple(dict.fromkeys(
            [item[0] for item in search["request_fields"] if isinstance(item, tuple)]
            + list(search.get("return_fields", []))
        ))

        yield {"type": "progress", "message": f"Datenquelle '{datasource}' wird verbunden"}

        if datasource == "api":
            metadata_source = tb_link_api(cred_path, "metadata")
            limit = test_mode_limit if test_mode else metadata_source.numClips()
            clip_ids = metadata_source.clips(offset=offset, limit=limit)
            clip_stream = (metadata_source.getClip(clip_id) for clip_id in clip_ids)
            total = len(clip_ids)
            step = 1

        elif datasource == "csv":
            metadata_source = link_csv_file(cred_path, fields)
            limit = test_mode_limit if test_mode else None
            clip_stream = metadata_source.iter_clips(offset=offset, limit=limit)
            total = limit
            step = 1000

        match_count = 0
        clip_index = 0
        yield {
            "type": "start",
            "message": f"Suche '{search.get('name', '')}' gestartet",
        }

        for clip_index, clip_all_metadata in enumerate(clip_stream, start=1):
            if clip_index == 1 or clip_index % step == 0:
                if total:
                    message = f"Clip {clip_index:_} von {total:_}, {match_count:_} Treffer".replace("_", ".")
                else:
                    message = f"Clip {clip_index:_} wird durchsucht, {match_count:_} Treffer".replace("_", ".")
                yield {"type": "progress", "message": message}

            match = eval_requests(clip_all_metadata, search["request_fields"])

            if match:
                match_count += 1
                return_row = []
                for field in search.get("return_fields", []):
                    return_values = find_all_field_values(clip_all_metadata, field)
                    return_row.append("; ".join(str(value) for value in return_values))

                yield {
                    "type": "match",
                    "message": return_row,
                }

        yield {
            "type": "end",
            "message": f"Suche '{search.get('name', '')}' beendet, {clip_index:_} Clips geprüft, {match_count:_} Treffer gefunden.".replace("_", "."),
        }

    except Exception as exc:
        yield {
            "type": "error",
            "message": f"Unhandled error in searcher: {exc}",
            "traceback": traceback.format_exc(),
        }


# --------- CONFIG ---------
datasource  = "csv"     # "api"
mode        = "real"    # "test 0 100"
cred_path = Path(__file__).parent / "cred.env"


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

    for search in searches:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        result_csv = tb_make_path(Path(__file__).parent, "searches", search["name"], f"result_{timestamp}.csv")

        with open(result_csv, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(search["return_fields"])

            progress_open = False

            for event in searcher(cred_path, datasource, search, mode):
                if event["type"] == "progress":
                    print(f"\r{event['message']:<60}", end="", flush=True)
                    progress_open = True
                    continue

                if event["type"] == "match":
                    writer.writerow(event["message"])
                    continue

                if progress_open:
                    print()
                    progress_open = False

                if event["type"] == "start":
                    print(event["message"])
                    tb_write_log(main_log, event["message"])

                elif event["type"] == "end":
                    print(event["message"])
                    tb_write_log(main_log, event["message"])

                elif event["type"] == "error":
                    print(event["message"])
                    tb_write_log(main_log, event["message"])
                    tb_write_log(main_log, event["traceback"])
