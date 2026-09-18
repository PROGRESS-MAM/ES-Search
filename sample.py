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
        "name": "progress_overview",
        "request_fields": (
            ("custom_metadata.009 Upload Veritone", "is", "True"),
        ),
        "return_fields": (
            "custom_metadata.038 Medium Type",
            "asset.asset_type_text",
            "custom_metadata.001 Identifier",
            "custom_metadata.006 Source PROGRESS",
            "custom_metadata.007 Collection PROGRESS",
            "custom_metadata.009 Upload Veritone",
            "custom_metadata.009a Progress Archive URL",
            "custom_metadata.009b Veritone Asset ID",
            "custom_metadata.014 Title Original",
            "custom_metadata.015 Title German",
            "custom_metadata.048 Rights Status",
            "custom_metadata.048b Notes Rights Status",
            "custom_metadata.049 Rights Owner.[]",
            "custom_metadata.052 Third Party Rights",
            "custom_metadata.053 Notes 3rd Party Rights",
            "custom_metadata.074a Country Of Action German.[]",
            "custom_metadata.076a City Of Action German",
            "custom_metadata.080 Production Year",
            "custom_metadata.082 Shoot Year",
            "custom_metadata.084 Decade.[]",
            "custom_metadata.098a Summary German",
            "custom_metadata.099a Shotlist German",
            "custom_metadata.100a Keywords German",
            "custom_metadata.101a Genre German.[]",
            "custom_metadata.102a Personalities German",
            "custom_metadata.103a Personalities Secondary German",
            "video.[].timecode_duration",
            "video.[].frame_rate",
            "has_audio",
            "has_video",
            "custom_metadata.031a Main Language German",
            "custom_metadata.029a Language Audio German.[]",
        ),
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
