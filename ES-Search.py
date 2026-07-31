# --------- IMPORTS ---------
from FUNC_LIB import get_cred, make_log, write_log
from operator import itemgetter
import FlowAPI
from pathlib import Path
import datetime
import json


# --------- CONFIG ---------
test_mode = True

search_fields = {"Path": "userpath"}
return_fields = {"Name": "display_name", "Hash": "hash", "Duration": "timecode_duration"}


# --------- INIT ---------
metadata_api = FlowAPI.Metadata.create_gateway_instance(
    get_cred("flow_user"),
    get_cred("flow_password"),
    get_cred("flow_host")
    )

main_log = make_log("searcher_log.txt")
write_log(main_log, f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}: Searcher started.")


# --------- FUNC ---------
def set_limit():
    """
    Set the limit for the number of clips to retrieve based on test mode.
    """
    if test_mode:
        return 10
    else:
        return metadata_api.numClips()


def find_all_matches(obj, match_key, results=None):
    """
    Recursively finds all values matching match_key in the given object.
    """
    if results is None:
        results = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == match_key:
                results.append(value)
            find_all_matches(value, match_key, results)
    elif isinstance(obj, list):
        for item in obj:
            find_all_matches(item, match_key, results)
    return results


# --------- MAIN ---------
limit = set_limit()
clip_ID = metadata_api.clips(offset=0, limit=limit)
clip_metadata = metadata_api.getClipsByIDs(clip_ID)


#print(find_all_matches(clip_metadata, search_fields["Path"]))

print(find_all_matches(clip_metadata, return_fields["Duration"]))



