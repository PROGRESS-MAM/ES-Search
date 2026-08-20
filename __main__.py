######################## SAMPLE IMPLEMENTATION ###############################

# --------- IMPORTS ---------
from toolbox import tb_write_log, tb_make_path
from .searcher import app_name, app_version, main_log, link, find
import datetime
import csv
from pathlib import Path


# --------- CONFIG ---------
metadata_source = "csv" # "api"
cred_path = Path(__file__).parent / "cred.env"
offset = 0
limit = False


# --------- SEARCHES ---------
searches = [
    {
        "name": "LTO Content",
        "request_fields": (
            ("display_backups", "is", "LS1901L7"),
        ),
        "return_fields": ("clip_id", "media_space_name", "display_name", "hash", "userpath", "display_backups"),
    }
]


# --------- EXEC ---------
if __name__ == "__main__":
    tb_write_log(main_log, f"{app_name} {app_version} started.")

    def print_progress(message: str) -> None:
        print(f"\r{message:<60}", end="", flush=True)

    link(metadata_source, cred_path, offset=offset, limit=limit, on_progress=print_progress)

    for search in searches:
        match, progress, error = find(search)
        print()

        if error:
            print(error)
            tb_write_log(main_log, error)
            continue

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        result_csv = tb_make_path(Path(__file__).parent, "searches", search["name"], f"result_{timestamp}.csv")

        with open(result_csv, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(search["return_fields"])
            writer.writerows(match)

        print(progress)
        tb_write_log(main_log, progress)
