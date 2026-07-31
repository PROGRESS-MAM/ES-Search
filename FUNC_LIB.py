# --------- IMPORTS ---------
import os
from dotenv import load_dotenv
from pathlib import Path



# --------- FUNC HELPER---------
def get_cred():
    """
    Load Flow credentials from cred.env and set them as environment variables.
    """
    env_path = Path(__file__).parent / "cred.env"
    load_dotenv(env_path)






# --------- FUNC MAIN---------
def get_flow_cred():
    """
    Retrieve Flow credentials from environment variables and return them as a dictionary.
    Usage in caller: *itemgetter("flow_host", "flow_user", "flow_password")(get_cred())
    """
    get_cred()
    return {
        "flow_host": os.environ.get("FLOW_HOST"),
        "flow_user": os.environ.get("FLOW_USER"),
        "flow_password": os.environ.get("FLOW_PASSWORD"),
    }



