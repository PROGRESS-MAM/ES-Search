# --------- IMPORTS ---------
from FUNC_LIB import link_api, write_log, get_duration_hours_from_tc
from pathlib import Path
import traceback
import csv
from typing import Any


# --------- SEARCH ---------
searches = [
    {
        "name": "drone_search",
        "requests": (
            ("has_video", "is", "true"),
            "and",
            ("userpath", "contains", ("Drohne", "Drone", "DJI", "drohne", "drone", "dji")),
        ),
        "returns": ("clip_id", "display_name", "hash", "timecode_start", "timecode_end", "userpath"),
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
def get_request(request):
    if isinstance(request, tuple):
        look_for_field, with_operator, for_value = request
        return look_for_field, with_operator, for_value
    else:
        requests_operator = request
        return requests_operator


def _get_field_value(clip_metadata: dict, field: str) -> Any:
    # try direct lookup
    if field in clip_metadata:
        return clip_metadata[field]

    # common nested location
    if isinstance(clip_metadata.get("metadata"), dict) and field in clip_metadata.get("metadata"):
        return clip_metadata.get("metadata").get(field)

    # case-insensitive search at top level
    for k, v in clip_metadata.items():
        if isinstance(k, str) and k.lower() == field.lower():
            return v

    # not found
    return None


def eval_single_request(clip_metadata: dict, request_tuple: tuple) -> bool:
    field, operator, value = request_tuple
    actual = _get_field_value(clip_metadata, field)

    # normalize
    if actual is None:
        return False

    # string comparisons
    if operator == "is":
        try:
            return str(actual).lower() == str(value).lower()
        except Exception:
            return actual == value

    if operator == "contains":
        # support value being tuple/list or single
        candidates = value if isinstance(value, (list, tuple)) else (value,)
        actual_str = str(actual).lower()
        for cand in candidates:
            if str(cand).lower() in actual_str:
                return True
        return False

    # numeric comparisons
    if operator in (">", "<", ">=", "<="):
        try:
            actual_num = float(actual)
            value_num = float(value)
            if operator == ">":
                return actual_num > value_num
            if operator == "<":
                return actual_num < value_num
            if operator == ">=":
                return actual_num >= value_num
            if operator == "<=":
                return actual_num <= value_num
        except Exception:
            return False

    # unknown operator — fail safe
    return False


def eval_requests_sequence(clip_metadata: dict, requests_sequence: tuple) -> bool:
    # supports alternating request tuples and operator strings ('and'/'or')
    results = []
    operators = []

    for req in requests_sequence:
        if isinstance(req, tuple):
            results.append(eval_single_request(clip_metadata, req))
        elif isinstance(req, str):
            operators.append(req.lower())
        else:
            # unsupported element
            operators.append(str(req).lower())

    if not results:
        return False

    # fold results with operators left-to-right
    acc = results[0]
    for idx, op in enumerate(operators):
        next_val = results[idx + 1] if idx + 1 < len(results) else False
        if op == "and":
            acc = acc and next_val
        elif op == "or":
            acc = acc or next_val
        else:
            # unknown operator: default to and
            acc = acc and next_val

    return acc



# --------- MAIN ---------
try:
    limit = 1 if test_mode else metadata_api.numClips()
    all_clip_ids = metadata_api.clips(offset=0, limit=limit)

    write_log(main_log, f"searches type: {type(searches)}")
    write_log(main_log, f"searches repr: {repr(searches)}")
    for search in searches:
        search_name = search["name"]
        result_csv = Path(__file__).parent / f"{search_name}_result.csv"

        # remove previous results once per search
        if result_csv.exists():
            result_csv.unlink()

        # iterate clips and evaluate requests
        for clip_id in all_clip_ids:
            clip_all_metadata = metadata_api.getClip(clip_id)

            try:
                matched = eval_requests_sequence(clip_all_metadata, search["requests"])
            except Exception as e:
                write_log(main_log, f"Error evaluating requests for clip {clip_id}: {e}")
                matched = False

            if matched:
                # prepare CSV header if needed
                write_header = not result_csv.exists()
                with open(result_csv, "a", newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    if write_header:
                        writer.writerow(list(search.get("returns", [])))

                    row = []
                    for field in search.get("returns", []):
                        val = _get_field_value(clip_all_metadata, field)
                        # flatten lists/dicts to string
                        if isinstance(val, (list, dict)):
                            row.append(str(val))
                        else:
                            row.append(val)
                    writer.writerow(row)
                write_log(main_log, f"Match for search '{search_name}' in clip {clip_id}")






except Exception as exc:
    error_message = f"Unhandled error: {exc}"
    print(error_message)
    write_log(main_log, error_message)
    write_log(main_log, traceback.format_exc())
    raise