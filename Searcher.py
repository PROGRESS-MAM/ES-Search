# --------- IMPORTS ---------
from toolbox import tb_link_api, tb_write_log, tb_make_path
import traceback
import json
from typing import Any, Dict, Iterator, List, Optional 
import datetime
import csv
from dotenv import load_dotenv
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import subprocess


# --------- STATIC ---------
app_name = "Searcher"
app_version = "0.4"
main_log = "searcher.log"

cred_path = Path(__file__).parent / "cred.env"
csv_path = Path("SMB File Exchange") / "CSV"
csv_file = "all_clips_all_metadata.csv"


# --------- CLASS ---------
class CsvMetadataSource:
    ENCODING = "utf-8-sig"
    DELIMITER = ","

    def __init__(self, csv_path, nest_keys: bool = True) -> None:
        self.csv_path = str(csv_path)
        self.nest_keys = nest_keys
        self.fieldnames = self._read_fieldnames()
        self._row_count: Optional[int] = None
        self._cursor: int = -1
        self._iterator: Optional[Iterator[Dict[str, Any]]] = None

    def _open(self):
        return open(self.csv_path, "r", newline="", encoding=self.ENCODING)

    def _read_fieldnames(self) -> List[str]:
        with self._open() as csvfile:
            return csv.DictReader(csvfile, delimiter=self.DELIMITER).fieldnames

    @staticmethod
    def _nest(row: Dict[str, str]) -> Dict[str, Any]:
        nested: Dict[str, Any] = {}
        for key, value in row.items():
            branch = nested
            *path, leaf = key.split(".")
            for segment in path:
                node = branch.get(segment)
                if not isinstance(node, dict):
                    node = {}
                    branch[segment] = node
                branch = node
            branch[leaf] = value
        return nested

    def _iter_rows(self) -> Iterator[Dict[str, Any]]:
        with self._open() as csvfile:
            for row in csv.DictReader(csvfile, delimiter=self.DELIMITER):
                row = {key.strip(): (value or "").strip()
                       for key, value in row.items() if key is not None}
                yield self._nest(row) if self.nest_keys else row

    def numClips(self) -> int:
        if self._row_count is None:
            with self._open() as csvfile:
                self._row_count = sum(1 for _ in csv.reader(csvfile, delimiter=self.DELIMITER)) - 1
        return max(0, self._row_count)

    def clips(self, offset: int = 0, limit: Optional[int] = None) -> List[int]:
        total = self.numClips()
        stop = total if limit is None else min(total, offset + limit)
        return list(range(min(offset, total), stop))

    def getClip(self, clip_id: int) -> Dict[str, Any]:
        if self._iterator is None or clip_id <= self._cursor:
            self._iterator = self._iter_rows()
            self._cursor = -1

        row: Optional[Dict[str, Any]] = None
        while self._cursor < clip_id:
            try:
                row = next(self._iterator)
            except StopIteration:
                raise IndexError(f"Clip-ID {clip_id} liegt hinter dem Ende der CSV.") from None
            self._cursor += 1

        if row is None:
            raise IndexError(f"Clip-ID {clip_id} konnte nicht gelesen werden.")
        return row

    def __len__(self) -> int:
        return self.numClips()

    def __repr__(self) -> str:
        return f"CsvMetadataSource({self.csv_path!r}, {len(self.fieldnames)} Felder)"


# --------- FUNC ---------
def link_csv_file() -> CsvMetadataSource:
    load_dotenv(cred_path, override=True)
    host = os.environ.get("CSV_HOST")
    user = os.environ.get("CSV_USER")
    password = os.environ.get("CSV_PASSWORD")
    mount = "/mnt"

    parts = (*csv_path.parts, csv_file)

    if os.name == "nt":
        full_path = Path(PureWindowsPath(f"//{host}", *parts))
    else:
        full_path = Path(PurePosixPath(mount, host, *parts))

    if os.name == "nt" and user:
        share = f"\\\\{host}\\IPC$"
        command = ["net", "use", share, password, f"/user:{user}", "/persistent:no"]
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"net use fehlgeschlagen: {result.stdout} {result.stderr}")

    return CsvMetadataSource(full_path)

def find_all_field_values(metadata: Any, field: str) -> List[Any]:
    seen = set()
    results = []

    def norm(v: Any) -> str:
        try:
            if isinstance(v, (dict, list, tuple)):
                return json.dumps(v, sort_keys=True, ensure_ascii=False)
            if isinstance(v, str):
                return v.casefold()
            return str(v)
        except Exception:
            return str(v)

    def recurse(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                try:
                    if isinstance(k, str) and k.casefold() == field.casefold():
                        key = norm(v)
                        if key not in seen:
                            seen.add(key)
                            results.append(v)
                except Exception:
                    pass
                recurse(v)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                recurse(item)

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
def searcher(datasource: str = None, search: dict = None, mode: str = "test 0 10") -> Iterator[Dict[str, object]]:
    try:
        mode_parts = mode.split()
        if mode_parts[0] == "real":
            test_mode = False
            offset = 0
        else:
            test_mode = True
            offset = int(mode_parts[1])
            test_mode_limit = int(mode_parts[2])

        if datasource == "api":
            metadata_source = tb_link_api("metadata")

        elif datasource == "csv":
            metadata_source = link_csv_file()

        limit = test_mode_limit if test_mode else metadata_source.numClips()
        clip_ids = metadata_source.clips(offset=offset, limit=limit)

        match_count = 0
        yield {
            "type": "start",
            "message": f"Suche '{search.get('name', '')}' gestartet",
        }

        for clip_index, clip_id in enumerate(clip_ids, start=1):
            yield {
                "type": "progress",
                "message": f"Clip {clip_index} von {len(clip_ids)} wird durchsucht",
            }

            clip_all_metadata = metadata_source.getClip(clip_id)
            match = eval_requests(clip_all_metadata, search["request_fields"])

            if match:
                match_count += 1
                return_row = []
                for field in search.get("return_fields", []):
                    return_values = find_all_field_values(clip_all_metadata, field)
                    if not return_values:
                        return_row.append("")
                    else:
                        return_row.append("; ".join(str(value) for value in return_values))

                yield {
                    "type": "match",
                    "message": return_row,
                }

        yield {
            "type": "end",
            "message": f"Suche '{search.get('name', '')}' beendet, {match_count} Treffer gefunden.",
        }

    except Exception as exc:
        yield {
            "type": "error",
            "message": f"Unhandled error in searcher: {exc}",
            "traceback": traceback.format_exc(),
        }





# --------- CONFIG ---------
#datasource = "api"
datasource = "csv"
mode = "test 0 10"
#mode = "real"

# --------- SEARCHES ---------
searches = [
    {
        "name": "Drone",
        "request_fields": (
            ("has_video", "is", "true"),
            "and",
            ("userpath", "contains", ("Drone", "Drohne", "DJI")),
        ),
        "return_fields": ("clip_id", "media_space_name", "display_name", "hash", "timecode_start", "timecode_end", "userpath"),
    }
]

# --------- EXEC ---------
if __name__ == "__main__":
    tb_write_log(main_log, f"{app_name} {app_version} started.")

    for search in searches:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        result_csv = tb_make_path("searches", search["name"], f"result_{timestamp}.csv")

        with open(result_csv, "w", newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(search["return_fields"])

        for event in searcher(datasource, search, mode):
            if event["type"] == "start":
                print(event["message"])
                tb_write_log(main_log, event["message"])

            elif event["type"] == "progress":
                print(event["message"])

            elif event["type"] == "match":
                with open(result_csv, "a", newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(event["message"])

            elif event["type"] == "end":
                print(event["message"])
                tb_write_log(main_log, event["message"])

            elif event["type"] == "error":
                print(event["message"])
                tb_write_log(main_log, event["message"])
                tb_write_log(main_log, event["traceback"])
