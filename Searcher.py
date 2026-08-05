# --------- IMPORTS ---------
from TOOLBOX.TOOLBOX import tb_link_api, tb_write_log, tb_make_path
import traceback
import json
from typing import Any, Dict, Iterator, List
import csv


# --------- CONFIG ---------
app_name = "Searcher"
app_version = "0.2"
main_log = "searcher.log"
test_mode = False
test_mode_limit = 10
datasource = "api"


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
def searcher(source: str = None, search: dict = None) -> Iterator[Dict[str, object]]:
    try:
        if source == "api":
            metadata_source = tb_link_api("metadata")
            limit = test_mode_limit if test_mode else metadata_source.numClips()
            clip_ids = metadata_source.clips(offset=0, limit=limit)

        elif source == "csv":
            # metadata_source = link csv file
            # limit = test_mode_limit if test_mode else all entries
            # clip_ids = get all metadata entries from csv
            pass

        match_count = 0
        yield {
            "type": "start",
            "message": f"Suche '{search.get("name", "")}' gestartet",
        }

        for clip_index, clip_id in enumerate(clip_ids, start=1):
            yield {
                "type": "progress",
                "message": f"Clip {clip_index} von {len(clip_ids)} wird durchsucht",
            }

            if source == "api":
                clip_all_metadata = metadata_source.getClip(clip_id)
            elif source == "csv":
                # clip_all_metadata = read clip metadata from csv
                pass

            match = eval_requests(clip_all_metadata, search["request_fields"])

            if match:
                match_count += 1
                return_row = []
                for field in search.get("returns", []):
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
            "message": f"Suche '{search.get("name", "")}' beendet, {match_count} Treffer gefunden.",
        }

    except Exception as exc:
        yield {
            "type": "error",
            "message": f"Unhandled error in searcher: {exc}",
            "traceback": traceback.format_exc(),
        }


# --------- EXEC ---------
if __name__ == "__main__":
    tb_write_log(main_log, f"{app_name} {app_version} started.")

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

    for search in searches:
        result_csv = tb_make_path("searches", search["name"], "result.csv")

        if result_csv.exists():
            result_csv.unlink()

        with open(result_csv, "w", newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(search["return_fields"])

        for event in searcher(datasource, search):
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

 