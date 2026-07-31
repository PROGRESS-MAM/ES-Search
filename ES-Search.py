# --------- IMPORTS ---------
from FUNC_LIB import get_cred, make_log, write_log
from operator import itemgetter
import FlowAPI
from pathlib import Path
import datetime
import json


# --------- CONFIG ---------
test_mode = True

search_fields = {}
return_fields = {}


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
        return 1
    else:
        return metadata_api.numClips()


# --------- MAIN ---------
limit = set_limit()
clip_ID = metadata_api.clips(offset=336549, limit=limit)
clip_ID = [1863759]
clip_metadata = metadata_api.getClipsByIDs(clip_ID)




