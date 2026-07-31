# --------- IMPORTS ---------
import os
from dotenv import load_dotenv
from pathlib import Path
import json




# --------- FUNC HELPER---------
def parse_tc_to_ms(tc_value):
    time_part, _ = tc_value.rsplit("/", 1)
    parts = time_part.split(":")

    hh, mm, ss, ff, fps = parts
    hh = int(hh)
    mm = int(mm)
    ss = int(ss)
    ff = int(ff)
    fps = int(fps)

    total_seconds = hh * 3600 + mm * 60 + ss
    frame_duration_seconds = 1 / fps
    total_ms = int((total_seconds * 1000) + (ff * frame_duration_seconds * 1000))
    return total_ms



# --------- FUNC MAIN---------
def get_cred(cred):
    """
    Load credentials from cred.env and return a single credential value.
    Usage in Caller e.g. "get_cred("flow_host")"
    """
    env_path = Path(__file__).parent / "cred.env"
    load_dotenv(env_path)

    if cred == "flow_host":
        return os.environ.get("FLOW_HOST")
    elif cred == "flow_user":
        return os.environ.get("FLOW_USER")
    elif cred == "flow_password":
        return os.environ.get("FLOW_PASSWORD")



def make_log(log_name="log.txt"):
    """
    Create a log file in the same directory as this script.
    """
    log_path = Path(__file__).parent / log_name
    log_path.touch(exist_ok=True)
    return log_path


def write_log(log_path, message):
    """
    Write a message to a log file.
    """
    with open(log_path, "a") as log_file:
        log_file.write(message + "\n")


def save_clip_metadata_to_json(clip_metadata):
    """
    Save clip metadata to a JSON file.
    """
    try:
        clip_id = clip_metadata[0]["clip_id"]
    except ():
        clip_id = "unknown_clip_id"

    file_name = f"clip_metadata_{clip_id}.json"
    with open(file_name, "w", encoding="utf-8") as file:
        json.dump(clip_metadata, file, ensure_ascii=False, indent=4)


def get_duration_hours_from_tc(tc_start, tc_end):
    if tc_start is None or tc_end is None:
        return None
    
    start_ms = parse_tc_to_ms(tc_start)
    end_ms = parse_tc_to_ms(tc_end)
    diff = end_ms - start_ms
    seconds = diff / 1000.0
    hours = seconds / 3600.0
    return f"{hours:.4f}"
