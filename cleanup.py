from pathlib import Path
import csv
from FUNC_LIB import get_duration_hours_from_tc


result_csv = Path("search_result_filtered.csv")

sum_hours = 0.0

with result_csv.open(newline="", encoding="utf-8") as csv_file:
    reader = csv.DictReader(csv_file)
    fieldnames = reader.fieldnames or []
    return_fields = {name: name for name in fieldnames if name != "total_duration_hours"}
    rows = list(reader)

for row in rows:
    duration_hours = get_duration_hours_from_tc(row.get("TC_start"), row.get("TC_end"))
    if duration_hours is not None:
        sum_hours += float(duration_hours)

output_fieldnames = list(return_fields.keys()) + ["total_duration_hours"]

with result_csv.open("a", newline="", encoding="utf-8") as csv_file:
    writer = csv.DictWriter(csv_file, fieldnames=output_fieldnames)
    row = {name: "" for name in return_fields.keys()}
    row["total_duration_hours"] = f"{sum_hours:.4f}"
    writer.writerow(row)

