# --------- IMPORTS ---------
from FUNC_LIB import get_cred, make_log, write_log, get_duration_hours_from_tc
import FlowAPI
from pathlib import Path
import datetime
import csv


# --------- CONFIG ---------
test_mode = True

search_fields = {"Path": "userpath", "Search_Phrase": ("Drohne", "Drone", "DJI", "MXF")}
return_fields = {"clip_ID": "clip_id", "Names": "display_name", "Hashes": "hash", "TC_start": "timecode_start", "TC_end": "timecode_end"}

main_log = make_log("searcher_log.txt")
result_csv = Path(__file__).parent / "search_result.csv"


# --------- INIT ---------
metadata_api = FlowAPI.Metadata.create_gateway_instance(
    get_cred("flow_user"),
    get_cred("flow_password"),
    get_cred("flow_host")
    )


write_log(main_log, f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}: Searcher started.")


# --------- FUNC ---------
def set_limit_and_offset():
    """
    Set the limit for the number of clips to retrieve based on test mode.
    """
    if test_mode:
        limit = 1
        offset = 0
    else:
        limit = 1000
        offset = 0

    return limit, offset


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
if result_csv.exists():
    result_csv.unlink()

limit, offset = set_limit_and_offset()
all_clips = metadata_api.numClips()
processed_batches = 0

while offset < all_clips:
    clip_ids = metadata_api.clips(offset=offset, limit=limit)
    all_clip_metadata = metadata_api.getClipsByIDs(clip_ids)

    for clip in all_clip_metadata:
        for path in find_all_matches(clip, search_fields["Path"]):
            if path and any(phrase in path for phrase in search_fields["Search_Phrase"]):
                write_return_items_to_csv(get_return_items(clip, return_fields))
                break

    processed_batches += 1
    print(f"Processed batch {processed_batches} of {((all_clips + limit - 1) // limit)} (current={offset}, total_clips={all_clips})")
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