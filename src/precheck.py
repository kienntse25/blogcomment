import csv, requests

HEADERS = {"User-Agent": "Mozilla/5.0"}

def has_comment_form(html: str) -> bool:
    return "textarea" in html.lower() and ("comment" in html.lower() or "id=\"comment\"" in html.lower())

def precheck_csv(input_file, output_ok, output_fail):
    with open(input_file, newline="") as f, \
         open(output_ok, "w", newline="") as okf, \
         open(output_fail, "w", newline="") as failf:

        reader = csv.DictReader(f)
        ok_writer = csv.DictWriter(okf, fieldnames=reader.fieldnames)
        fail_writer = csv.DictWriter(failf, fieldnames=reader.fieldnames + ["reason"])

        ok_writer.writeheader()
        fail_writer.writeheader()

        for row in reader:
            try:
                resp = requests.get(row["URL"], timeout=10, headers=HEADERS)
                if resp.status_code >= 400:
                    row["reason"] = f"status_{resp.status_code}"
                    fail_writer.writerow(row)
                elif has_comment_form(resp.text):
                    ok_writer.writerow(row)
                else:
                    row["reason"] = "no_form"
                    fail_writer.writerow(row)
            except Exception as e:
                row["reason"] = type(e).__name__
                fail_writer.writerow(row)
