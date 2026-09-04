######################## SAMPLE IMPLEMENTATION ###############################

# --------- IMPORTS ---------
from toolbox import tb_link_api, tb_write_log, tb_make_path
import searcher
import datetime
import csv
from pathlib import Path


# --------- STATIC ---------
app_name = "Search Runner"
app_version = "0.1"

base_path = Path(__file__).parent
main_log = base_path / "searcher.log"
cred_path = base_path / "cred.env"
result_folder = "searches"


# --------- CONFIG ---------
metadata_source = "file"    # "file" (Parquet auf dem Share) oder "api"


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
    tb_write_log(main_log, f"{app_name} {app_version} started, "
                           f"{searcher.app_name} {searcher.app_version} verlinkt.")

    def print_progress(message: str) -> None:
        print(f"\r{message:<80}", end="", flush=True)

    searcher.link(metadata_source, cred_path, on_progress=print_progress,
                  api_link=lambda: tb_link_api(cred_path, "metadata"))

    for search in searches:
        match, progress, error = searcher.find(search)
        print()

        if error:
            print(error)
            tb_write_log(main_log, error)
            continue

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        search_name = search["name"]
        result_file = tb_make_path(base_path, result_folder,
                                   f"{search_name}_result_{timestamp}.csv")

        with open(result_file, "w", newline="", encoding="utf-8-sig") as result_handle:
            writer = csv.writer(result_handle)
            writer.writerow(search["return_fields"])
            writer.writerows(match)
            
        tb_write_log(main_log, progress)
