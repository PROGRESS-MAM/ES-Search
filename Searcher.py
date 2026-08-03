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
        "name": "drone_search",
        "requests": (
            ("has_video", "is", "true"),
            "and",
            ("userpath", "contains", ("Drohne", "Drone", "DJI")),
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

                write_log(main_log, f"Match for search '{search_name}' in clip {clip_id}")

except Exception as exc:
    error_message = f"Unhandled error: {exc}"
    print(error_message)
    write_log(main_log, error_message)
    write_log(main_log, traceback.format_exc())
    raise