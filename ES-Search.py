# --------- IMPORTS ---------
from FUNC_LIB import link_api, make_log, write_log, get_duration_hours_from_tc
import FlowAPI
from pathlib import Path
import csv
import traceback


# --------- CONFIG ---------
test_mode = True


searches = (
    {
        "name": "drone_search", 
        "search_field": "userpath",
        "search_method": "contains",
        "search_values": ("Drohne", "Drone", "DJI", "drohne", "drone", "dji"),
        "condition_field": "has_video",
        "condition_method": "is",
        "condition_value": "true",
        "return_values": ("clip_id", "display_name", "hash", "timecode_start", "timecode_end", "userpath")
    }
)

main_log = make_log("searcher_log.txt")
result_csv = Path(__file__).parent / "search_result.csv"


# --------- INIT ---------
metadata_api = link_api("metadata")

write_log(main_log, "Searcher started.")

# --------- FUNC ---------
def find_all_matches(obj, match_key, results=None):
    """
    Recursively finds all values matching match_key in the given object.
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


# --------- MAIN ---------
search_info_message = (
    f"Searching in field '{search_fields['Path']}' for: {', '.join(search_fields['Search_Phrase'])}"
)
print("Search started")
print(search_info_message)
write_log(main_log, f"{search_info_message}")

try:
    if result_csv.exists():
        result_csv.unlink()

    limit = 1 if test_mode else metadata_api.numClips()

    all_clip_ids = metadata_api.clips(offset=0, limit=limit)

    for clip_id in all_clip_ids:
        clip_all_metadata = metadata_api.getClip(clip_id)
        
        for metadata in clip_all_metadata:
            if metadata == has video // condition
                for path in find_all_matches(metadata, search_fields["Path"]):
                    if path and any(phrase in path for phrase in condition_fields["Search_Phrase"]):
                        write_return_items_to_csv(get_return_items(metadata, return_fields))
                        break

        progress_message = f""
        print(progress_message)
        write_log(main_log, progress_message)
        offset += limit






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
