# --------- IMPORTS ---------
from FUNC_LIB import link_api, write_log, get_duration_hours_from_tc
from pathlib import Path
import csv
import traceback


# --------- CONFIG ---------
searches = (
    {
        "name": "drone_search", 
        "requests": (
                    ("has_video", "is", "true"),
                    ("and"),
                    ("userpath", "contains", ("Drohne", "Drone", "DJI", "drohne", "drone", "dji"))
                    ),
        "returns": ("clip_id", "display_name", "hash", "timecode_start", "timecode_end", "userpath")
    }
)

test_mode = True
main_log = "searcher_log.txt"
result_csv = Path(__file__).parent / f"{searches['name']}_result.csv"


# --------- INIT ---------
metadata_api = link_api("metadata")
write_log(main_log, "Searcher started.")


# --------- FUNC ---------
def get_metadata_value(field, method, clip):
    """
    Recursively finds all values matching field with given method in clip.
    """
    if results is None:
        results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == match_key and value not in results:
                results.append(value)
            find_all_matches(value, match_key, results)
    elif isinstance(obj, list):
        for item in obj:
            find_all_matches(item, match_key, results)
    return results


def get_return_items(clip, fields):
    """
    Build a dictionary with all values from the configured return fields.
    """
    return_items = {}

    for name, field_name in fields.items():
        matches = find_all_matches(clip, field_name)
        if matches:
            return_items[name] = matches[0] if len(matches) == 1 else matches
        else:
            return_items[name] = None

    return return_items


def write_return_items_to_csv(return_items):
    """
    Append return items as a row to a CSV file.
    """
    fieldnames = list(return_fields.keys()) + ["total_duration_hours"]
    with open(result_csv, "a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if csv_file.tell() == 0:
            writer.writeheader()
        row = {name: return_items.get(name, "") for name in return_fields.keys()}
        row["total_duration_hours"] = ""
        writer.writerow(row)


def eval_method(left, method, right):
    if method == "is":
        return left == right

    elif method == "contains":
        return any(val in left for val in right)

    elif method == "and":
        return left and right

    else:
        raise ValueError(f"Unknown evaluation method: {method}")



# --------- MAIN ---------
try:
    if result_csv.exists():
        result_csv.unlink()

    limit = 1 if test_mode else metadata_api.numClips()

    all_clip_ids = metadata_api.clips(offset=0, limit=limit)

    for clip_id in all_clip_ids:
        clip_all_metadata = metadata_api.getClip(clip_id)

        for search in searches:
            for request in search["requests"]:
                

       

            meta = clip_all_metadata.get(s_field)

            if eval_method(meta, c_method, c_value):





                if clip_all_metadata[field] 






            if metadata == has video // condition
                for path in find_all_matches(metadata, search_fields["Path"]):
                    if path and any(phrase in path for phrase in condition_fields["Search_Phrase"]):
                        write_return_items_to_csv(get_return_items(metadata, return_fields))
                        break


  






    # Case: Get total hours from search
    sum_hours = 0.0

    with open(result_csv, newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    for row in rows:
        duration_hours = get_duration_hours_from_tc(row.get("TC_start"), row.get("TC_end"))
        if duration_hours is not None:
            sum_hours += float(duration_hours)

    fieldnames = list(return_fields.keys()) + ["total_duration_hours"]
    with open(result_csv, "a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        row = {name: "" for name in return_fields.keys()}
        row["total_duration_hours"] = f"{sum_hours:.4f}"
        writer.writerow(row)


except Exception as exc:
    error_message = f"Unhandled error: {exc}"
    print(error_message)
    write_log(main_log, error_message)
    write_log(main_log, traceback.format_exc())
    raise
