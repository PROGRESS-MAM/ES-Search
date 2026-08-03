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
        "name": "drone",
        "requests": (
            ("has_video", "is", "false"),
            "and",
            ("userpath", "contains", ("Drone", "mxf", "wav")),
        ),
        "return": ("clip_id", "display_name", "hash", "timecode_start", "timecode_end", "userpath"),
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
def find_all_field_values(data: Any, field: str) -> List[Any]:
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

    def _recurse(obj: Any):
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
                _recurse(v)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _recurse(item)

    _recurse(data)
    return results


def eval_single_request(clip_metadata: dict, request_tuple: tuple) -> bool:
    field, operator, value = request_tuple
    vals = find_all_field_values(clip_metadata, field)

    # no values found -> fail
    if not vals:
        return False

    # string comparisons
    if operator == "is":
        value_text = str(value).casefold()
        return any(str(val).casefold() == value_text for val in vals)

    if operator == "contains":
        candidates = value if isinstance(value, (list, tuple)) else (value,)
        return any(
            str(cand).casefold() in str(actual).casefold()
            for actual in vals
            for cand in candidates
        )


    # numeric comparisons
    if operator in (">", "<", ">=", "<="):
        try:
            value_num = float(value)
            for actual in vals:
                try:
                    actual_num = float(actual)
                except Exception:
                    continue
                if operator == ">" and actual_num > value_num:
                    return True
                if operator == "<" and actual_num < value_num:
                    return True
                if operator == ">=" and actual_num >= value_num:
                    return True
                if operator == "<=" and actual_num <= value_num:
                    return True
            return False
        except Exception:
            return False

    # unknown operator — fail safe
    return False


def eval_requests(data: dict, requests: tuple) -> bool:
    request = []
    request_operators = []

    for item in requests:
        if isinstance(item, tuple):
            request.append(eval_single_request(data, item))
        elif isinstance(item, str):
            request_operators.append(item)

    if not request:
        return False

    acc = request[0]
    for idx, operator in enumerate(request_operators):
        next_val = request[idx + 1] if idx + 1 < len(request) else False

        if operator == "and":
            acc = acc and next_val
        elif operator == "or":
            acc = acc or next_val
            
    return acc



# --------- MAIN ---------
try:
    limit = 10 if test_mode else metadata_api.numClips()
    all_clip_ids = metadata_api.clips(offset=0, limit=limit)

    for search in searches:
        for clip_id in all_clip_ids:
            clip_all_metadata = metadata_api.getClip(clip_id)
            matched = eval_requests(clip_all_metadata, search["requests"])

            if matched:
                search_name = search["name"]
                result_csv = Path(__file__).parent / f"{search_name}__search_result.csv"

                if result_csv.exists():
                    result_csv.unlink()

                write_header = not result_csv.exists()
                with open(result_csv, "a", newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    if write_header:
                        writer.writerow(list(search.get("return", [])))

                    row = []
                    for field in search.get("return", []):
                        vals = find_all_field_values(clip_all_metadata, field)
                        if not vals:
                                # no values found -> empty cell
                                row.append("")
                        else:
                            # stringify and deduplicate-preserving-order already done by find_all_field_values
                            flat = []
                            for v in vals:
                                if isinstance(v, (list, dict)):
                                    flat.append(json.dumps(v, ensure_ascii=False))
                                else:
                                    flat.append(str(v))
                            row.append("; ".join(flat))
                    writer.writerow(row)


except Exception as exc:
    error_message = f"Unhandled error: {exc}"
    print(error_message)
    write_log(main_log, error_message)
    write_log(main_log, traceback.format_exc())
    raise