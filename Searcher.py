# --------- IMPORTS ---------
from FUNC_LIB import link_api, write_log, get_duration_hours_from_tc
from pathlib import Path
import traceback
import json
from typing import Any, List
import csv


# --------- SEARCH ---------
searches = [
    {
        "name": "Drone",
        "requests": (
            ("has_video", "is", "true"),
            "and",
            ("userpath", "contains", ("Drone", "Drohne", "DJI")),
        ),
        "returns": ("clip_id", "media_space_name", "display_name", "hash", "timecode_start", "timecode_end", "userpath"),
    }
]


# --------- CONFIG ---------
app_name = "Searcher"
app_version = "0.1"
test_mode = True
main_log = "searcher_log.txt"



# --------- INIT ---------
metadata_api = link_api("metadata")
write_log(main_log, f"{app_name} {app_version} started.")


# --------- FUNC ---------
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
try:
    limit = 2 if test_mode else metadata_api.numClips()
    all_clip_ids = metadata_api.clips(offset=0, limit=limit)

    for search in searches:
        search_name = search["name"]
        result_csv = Path(__file__).parent / f"{search_name}__search_result.csv"
        match_count = 0

        start_message = f"Suche '{search_name}' gestartet"
        print(start_message)
        write_log(main_log, start_message)

        if result_csv.exists():
            result_csv.unlink()

        for clip_index, clip_id in enumerate(all_clip_ids, start=1):
            progress_message = f"Clip {clip_index} von {len(all_clip_ids)} durchsucht"
            print(progress_message)

            clip_all_metadata = metadata_api.getClip(clip_id)
            match = eval_requests(clip_all_metadata, search["requests"])

            if match:
                match_count += 1
                write_header = not result_csv.exists()

                with open(result_csv, "a", newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    if write_header:
                        writer.writerow(list(search.get("returns", [])))

                    row = []
                    for field in search.get("returns", []):
                        return_values = find_all_field_values(clip_all_metadata, field)
                        if not return_values:
                                row.append("")
                        else:
                            row.append("; ".join(str(value) for value in return_values))
                    writer.writerow(row)

        end_message = f"Suche '{search_name}' beendet, {match_count} Treffer gefunden."
        print(end_message)
        write_log(main_log, end_message)


except Exception as exc:
    error_message = f"Unhandled error: {exc}"
    print(error_message)
    write_log(main_log, error_message)
    write_log(main_log, traceback.format_exc())
    raise