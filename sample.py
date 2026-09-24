######################## SAMPLE IMPLEMENTATION ###############################

# --------- IMPORTS ---------
from toolbox import tb_link_api, tb_write_log, tb_make_path
import searcher
import datetime
import traceback
import csv
from pathlib import Path


# --------- CONFIG ---------
app_name = "Search Runner"
app_version = "0.1"

base_path = Path(__file__).parent
main_log = base_path / "searcher.log"
cred_path = base_path / "cred.env"
result_folder = "searches"


metadata_source = "file"    # "file" (Parquet auf dem Share) oder "api"


# --------- SEARCHES ---------
searches = [
    {
        "name": "AEP-Dateien im Mediaspace Oury Jalloh Render",
        "request_fields": (
            ("media_space_name", "is", "Oury Jalloh Render"),
            "and",
            ("userpath", "ends_with", ".aep"),
        ),
        "return_fields": ("clip_id", "media_space_name", "userpath"),
    }
]

# --------- MAIN ---------
def main() -> None:
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
                                   f"{timestamp}_{search_name}_result.csv")

        with open(result_file, "w", newline="", encoding="utf-8-sig") as result_handle:
            writer = csv.writer(result_handle)
            writer.writerow(search["return_fields"])
            writer.writerows(match)
            
        tb_write_log(main_log, progress)


# --------- EXEC ---------
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        error_message = f"Unhandled error in main: {exc}"
        print(error_message)
        tb_write_log(main_log, error_message)
        tb_write_log(main_log, traceback.format_exc())
