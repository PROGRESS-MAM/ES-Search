# --------- IMPORTS ---------
import os
from dotenv import load_dotenv
from pathlib import Path



# --------- FUNC HELPER---------








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