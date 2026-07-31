# --------- IMPORTS ---------
from FUNC_LIB import get_flow_cred
from operator import itemgetter
import FlowAPI
from pathlib import Path





# --------- INIT ---------
metadata_api = FlowAPI.Metadata.create_gateway_instance(
    *itemgetter("flow_host", "flow_user", "flow_password")(get_flow_cred())
)



# --------- CONFIG ---------
test_mode = True


search_fields = {}
result_fields = {}

log_path = Path(__file__).parent / "log.csv"




# --------- GLOBALS ---------
LIMIT = 0



# --------- FUNC ---------
def test_mode():
    global LIMIT

    if test_mode:
        print(" ~ ~ ~ Test mode is ON. ~ ~ ~")
        LIMIT = 10

    else:
        LIMIT  = metadata_api.numClips()




# --------- MAIN ---------
all_clips   = metadata_api.clips(offset=0, limit=LIMIT)
total_clips = len(all_clips)


