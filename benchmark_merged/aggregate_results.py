"""
Aggregate benchmark results from merged directory.
Usage: python aggregate_results.py benchmark_merged/
"""

import json
import sys
from pathlib import Path
from collections import Counter

results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmark_merged")

results = []
for f in sorted(results_dir.glob("*.json")):
    if f.name == "summary.json":
        continue
    try:
        results.append(json.loads(f.read_text()))
    except Exception as e:
        print(f"  Skipped {f.name}: {e}")

total = len(results)
successes = sum(1 for r in results if r.get("build_success"))
failures = total - successes

print(f"{'=' * 60}")
print(f"BENCHMARK RESULTS ({total} papers)")
print(f"{'=' * 60}")

print(f"\n  Success: {successes} ({100*successes/total:.1f}%)")
print(f"  Failure: {failures} ({100*failures/total:.1f}%)")

# Failure breakdown
print(f"\n  Failure breakdown:")
cats = Counter(r["failure_category"] for r in results if r.get("failure_category") and r["failure_category"] != "success")
for cat, count in cats.most_common():
    pct = 100 * count / total
    print(f"    {cat:30s}: {count:4d} ({pct:4.1f}%)")

# Failure by stage
print(f"\n  Failure by stage:")
stages = Counter(r["failure_stage"] for r in results if r.get("failure_stage"))
for stage, count in stages.most_common():
    print(f"    {stage:30s}: {count:4d}")

# By subfield
print(f"\n  By subfield:")
subfields = {}
for r in results:
    sf = r.get("subfield", "unknown")
    if sf not in subfields:
        subfields[sf] = {"success": 0, "failure": 0}
    subfields[sf]["success" if r.get("build_success") else "failure"] += 1

for sf, counts in sorted(subfields.items(), key=lambda x: -(x[1]["success"] + x[1]["failure"])):
    total_sf = counts["success"] + counts["failure"]
    rate = 100 * counts["success"] / total_sf if total_sf else 0
    print(f"    {sf:25s}: {counts['success']:3d}/{total_sf:3d} ({rate:4.1f}%)")

# By framework
print(f"\n  By framework:")
frameworks = {}
for r in results:
    fw = r.get("framework", "unknown")
    if fw not in frameworks:
        frameworks[fw] = {"success": 0, "failure": 0}
    frameworks[fw]["success" if r.get("build_success") else "failure"] += 1

for fw, counts in sorted(frameworks.items(), key=lambda x: -(x[1]["success"] + x[1]["failure"])):
    total_fw = counts["success"] + counts["failure"]
    rate = 100 * counts["success"] / total_fw if total_fw else 0
    print(f"    {fw:15s}: {counts['success']:3d}/{total_fw:3d} ({rate:4.1f}%)")

# By year
print(f"\n  By year:")
years = {}
for r in results:
    yr = r.get("year", 0)
    if yr not in years:
        years[yr] = {"success": 0, "failure": 0}
    years[yr]["success" if r.get("build_success") else "failure"] += 1

for yr, counts in sorted(years.items()):
    total_yr = counts["success"] + counts["failure"]
    rate = 100 * counts["success"] / total_yr if total_yr else 0
    print(f"    {yr}: {counts['success']:3d}/{total_yr:3d} ({rate:4.1f}%)")

# Duration stats
durations = [r["duration_seconds"] for r in results if r.get("duration_seconds")]
print(f"\n  Duration stats:")
print(f"    Mean: {sum(durations)/len(durations):.1f}s")
print(f"    Median: {sorted(durations)[len(durations)//2]:.1f}s")
print(f"    Max: {max(durations):.1f}s")
print(f"    Total: {sum(durations)/3600:.1f} hours")

# LLM usage
llm_calls = sum(r.get("llm_inferences_made", 0) for r in results)
llm_failed = sum(1 for r in results if r.get("dependencies_inferred_by_llm", 0) == 0 and r.get("env_file_found"))
print(f"\n  LLM usage:")
print(f"    Total inferences: {llm_calls}")
print(f"    Papers with env file but no LLM deps: {llm_failed}")

print(f"\n{'=' * 60}")
