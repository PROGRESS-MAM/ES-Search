import os
from dotenv import load_dotenv
from pathlib import Path


def get_flow_cred():
    """
    Load Flow credentials from cred.env and return them as a dict.
    Usage in caller: *itemgetter("flow_host", "flow_user", "flow_password")(get_cred())
    """
    env_path = Path(__file__).parent / "cred.env"
    load_dotenv(env_path)
    return {
        "flow_host": os.environ.get("FLOW_HOST"),
        "flow_user": os.environ.get("FLOW_USER"),
        "flow_password": os.environ.get("FLOW_PASSWORD"),
    }



