"""Stage 5b: merge narrative-workflow output into dashboard.json.

Usage: python3 -m scripts.merge_narratives <workflow_output_file.json>
"""
import json
import sys
import os

DATA = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/data"
DASH = f"{DATA}/dashboard.json"


def main(out_file):
    res = json.load(open(out_file))["result"]["narratives"]
    by_login = {n["login"]: n for n in res}
    dash = json.load(open(DASH))
    for e in dash["engineers"]:
        n = by_login.get(e["login"])
        if not n:
            continue
        e["narrative"] = n["narrative"]
        sm = {ev["number"]: ev["summary"] for ev in n.get("evidence", [])}
        for ev in e["evidence"]:
            if ev["pr"] in sm:
                ev["summary"] = sm[ev["pr"]]
    json.dump(dash, open(DASH, "w"), indent=2)
    print(f"merged narratives for {len(by_login)} engineers -> {DASH}")


if __name__ == "__main__":
    main(sys.argv[1])
