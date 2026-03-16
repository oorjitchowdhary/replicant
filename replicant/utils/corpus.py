"""
Corpus Selection for Replicant ACM REP '26 Benchmark
=====================================================

METHODOLOGY (for the paper):

  We constructed our evaluation corpus from the Papers with Code archive,
  a community-curated dataset linking research papers to their source code
  repositories. We used the final public snapshot (July 2025) released
  before the platform was discontinued by Meta.

  INCLUSION CRITERIA:
  1. Paper has an arXiv identifier (enables automated retrieval)
  2. Code repository is hosted on GitHub (our pipeline requires git clone)
  3. Repository link is author-provided ("official"), not a community
     reimplementation — we measure author reproducibility practices,
     not third-party reconstruction quality
  4. Paper published between 2022–2025 (recent enough to reflect current
     practices, old enough for repositories to be stable)

  STRATIFICATION:
  Papers were classified into CS subfields based on their PwC task
  annotations using keyword matching. We sampled proportionally to
  subfield representation in the eligible pool, with a minimum of 5
  papers per subfield to ensure coverage of smaller domains.

  DEDUPLICATION:
  Papers appearing multiple times (e.g., multiple linked repositories)
  were deduplicated by arXiv ID, retaining the first official repository.

  REPRODUCIBILITY:
  Sampling uses a fixed random seed (42). The complete corpus with
  metadata is provided as supplementary material.

Run:
    pip install datasets pandas pyarrow
    python select_corpus.py

Outputs:
    corpus_1000.csv  — benchmark input for `replicant benchmark`
    corpus_1000.json — same data in JSON
    corpus_methodology.json — full selection statistics for the paper
"""

import pandas as pd
import numpy as np
import json
from collections import Counter
from datasets import load_dataset

RANDOM_SEED = 42
TARGET_N = 1000
MIN_PER_SUBFIELD = 5
YEAR_RANGE = (2022, 2025)

# ─── 1. Load & filter links ─────────────────────────────────────────────────

print("=" * 60)
print("CORPUS SELECTION PIPELINE")
print("=" * 60)

print("\n[1/6] Loading PwC links dataset...")
links_ds = load_dataset("pwc-archive/links-between-paper-and-code", split="train")
links_df = links_ds.to_pandas()
total_links = len(links_df)
print(f"  Raw paper-code links: {total_links:,}")

# Criterion: official repos only
links_df = links_df[links_df["is_official"] == True].copy()
n_official = len(links_df)
print(f"  After filter (official only): {n_official:,}")

# Criterion: has arXiv ID
links_df = links_df[links_df["paper_arxiv_id"].notna()].copy()
n_arxiv = len(links_df)
print(f"  After filter (has arXiv ID): {n_arxiv:,}")

# Criterion: GitHub hosted
links_df["is_github"] = links_df["repo_url"].str.contains("github.com", na=False)
links_df = links_df[links_df["is_github"]].copy()
n_github = len(links_df)
print(f"  After filter (GitHub repos): {n_github:,}")

needed_ids = set(links_df["paper_arxiv_id"].dropna().unique())
print(f"  Unique arXiv IDs: {len(needed_ids):,}")
del links_ds

# ─── 2. Load papers & merge ─────────────────────────────────────────────────

print("\n[2/6] Loading papers dataset...")
papers_ds = load_dataset("pwc-archive/papers-with-abstracts", split="train")
papers_df = papers_ds.to_pandas()
total_papers = len(papers_df)
print(f"  Total papers in archive: {total_papers:,}")

papers_df = papers_df[papers_df["arxiv_id"].isin(needed_ids)].copy()
papers_df = papers_df[["arxiv_id", "conference", "tasks", "date", "proceeding"]].copy()
print(f"  Matched to our links: {len(papers_df):,}")
del papers_ds

print("\n[3/6] Merging datasets...")
merged = links_df.merge(papers_df, left_on="paper_arxiv_id", right_on="arxiv_id", how="inner")
del links_df, papers_df

merged["year"] = pd.to_datetime(merged["date"], errors="coerce").dt.year
print(f"  Merged rows: {len(merged):,}")

# Criterion: year range
recent = merged[(merged["year"] >= YEAR_RANGE[0]) & (merged["year"] <= YEAR_RANGE[1])].copy()
print(f"  After filter ({YEAR_RANGE[0]}-{YEAR_RANGE[1]}): {len(recent):,}")

# Deduplicate by arXiv ID
recent_dedup = recent.drop_duplicates(subset="paper_arxiv_id").copy()
print(f"  After dedup by arXiv ID: {len(recent_dedup):,}")

# ─── 3. Subfield classification ─────────────────────────────────────────────

print("\n[4/6] Classifying subfields...")


def categorize_subfield(tasks):
    """Map PwC task annotations to broad CS subfields via keyword matching."""
    if tasks is None:
        return "uncategorized"
    task_list = list(tasks) if hasattr(tasks, '__iter__') else []
    if len(task_list) == 0:
        return "uncategorized"

    for t in task_list:
        tl = str(t).lower()

        if any(kw in tl for kw in [
            "object detection", "image classif", "image segm", "semantic segm",
            "instance segm", "panoptic", "visual", "image gen", "super-resol",
            "depth estim", "pose estim", "face", "video", "point cloud",
            "3d", "scene", "optical flow", "style transfer", "image restor",
            "denois", "inpaint", "image caption", "salient", "action recogn",
            "gaze", "stereo", "image retriev", "image reconstruct", "image super",
            "object", "segmentation",
        ]):
            return "computer_vision"

        if any(kw in tl for kw in [
            "text classif", "sentiment", "named entity", "question answer",
            "machine translat", "summariz", "language model", "text gen",
            "relation extract", "natural language", "dialogue", "reading compreh",
            "word embed", "pars", "information extract", "sentence",
            "token classif", "coreference", "translat", "language",
            "document", "nli", "conversational", "chatbot",
        ]):
            return "nlp"

        if any(kw in tl for kw in [
            "speech", "audio", "voice", "speaker", "sound", "music", "acoustic",
        ]):
            return "audio_speech"

        if any(kw in tl for kw in [
            "reinforcement", "robot", "navigation", "game play", "control",
            "autonomous", "atari", "continuous control", "multi-agent", "planning",
        ]):
            return "rl_robotics"

        if any(kw in tl for kw in [
            "graph", "node classif", "link predict", "knowledge graph",
        ]):
            return "graph_ml"

        if any(kw in tl for kw in [
            "drug", "protein", "molecular", "medical", "clinical", "health",
            "cell", "biomedical", "genomic", "pathol", "radiol", "retina",
            "brain", "tumor",
        ]):
            return "bio_medical"

        if any(kw in tl for kw in [
            "time series", "time-series", "forecast", "anomaly detect",
        ]):
            return "time_series"

        if any(kw in tl for kw in [
            "recommend", "collaborative filter", "click-through",
        ]):
            return "recsys"

        if any(kw in tl for kw in [
            "code", "program synth", "software", "bug detect", "vulnerab",
        ]):
            return "code_se"

    return "other_ml"


recent_dedup["subfield"] = recent_dedup["tasks"].apply(categorize_subfield)

sf_counts = recent_dedup["subfield"].value_counts()
print("\n  Candidate pool by subfield:")
for sf, count in sf_counts.items():
    pct = 100 * count / len(recent_dedup)
    print(f"    {sf:25s}: {count:5d} ({pct:4.1f}%)")

# ─── 4. Stratified sampling ─────────────────────────────────────────────────

print(f"\n[5/6] Stratified sampling (target={TARGET_N}, min/subfield={MIN_PER_SUBFIELD})...")

subfields_with_enough = sf_counts[sf_counts >= MIN_PER_SUBFIELD].index.tolist()
total_eligible = sf_counts[subfields_with_enough].sum()

# Proportional allocation with minimum guarantee
allocation = {}
for sf in subfields_with_enough:
    prop = max(MIN_PER_SUBFIELD, round(TARGET_N * sf_counts[sf] / total_eligible))
    allocation[sf] = min(prop, sf_counts[sf])

# Trim to target if over-allocated
total_alloc = sum(allocation.values())
if total_alloc > TARGET_N:
    for sf in sorted(allocation, key=allocation.get, reverse=True):
        if total_alloc <= TARGET_N:
            break
        reduce_by = min(allocation[sf] - MIN_PER_SUBFIELD, total_alloc - TARGET_N)
        allocation[sf] -= reduce_by
        total_alloc -= reduce_by

# If under target, add to largest subfields
if total_alloc < TARGET_N:
    deficit = TARGET_N - total_alloc
    for sf in sorted(allocation, key=allocation.get, reverse=True):
        can_add = sf_counts[sf] - allocation[sf]
        add = min(can_add, deficit)
        allocation[sf] += add
        deficit -= add
        total_alloc += add
        if deficit <= 0:
            break

print("\n  Sampling allocation:")
for sf, n in sorted(allocation.items(), key=lambda x: -x[1]):
    pool_size = sf_counts[sf]
    print(f"    {sf:25s}: {n:4d} / {pool_size:5d} available")
print(f"    {'TOTAL':25s}: {sum(allocation.values()):4d}")

# Sample
corpus_frames = []
for sf, n in allocation.items():
    pool = recent_dedup[recent_dedup["subfield"] == sf]
    # Prefer papers where code was explicitly mentioned in the paper text
    mentioned = pool[pool["mentioned_in_paper"] == True]
    if len(mentioned) >= n:
        sample = mentioned.sample(n=n, random_state=RANDOM_SEED)
    else:
        rest = pool[pool["mentioned_in_paper"] == False]
        sample = pd.concat([
            mentioned,
            rest.sample(n=min(n - len(mentioned), len(rest)), random_state=RANDOM_SEED)
        ])
    corpus_frames.append(sample)

corpus = pd.concat(corpus_frames)
print(f"\n  Final corpus: {len(corpus)} papers")

# ─── 5. Summary statistics ──────────────────────────────────────────────────

print(f"\n[6/6] Corpus statistics...")

print(f"\n  By year:")
year_dist = corpus["year"].value_counts().sort_index()
for yr, count in year_dist.items():
    print(f"    {int(yr)}: {count:4d}")

print(f"\n  By subfield:")
sf_dist = corpus["subfield"].value_counts()
for sf, count in sf_dist.items():
    print(f"    {sf:25s}: {count:4d}")

print(f"\n  By framework:")
fw_dist = corpus["framework"].value_counts()
for fw, count in fw_dist.items():
    print(f"    {fw:15s}: {count:4d}")

# ─── 6. Output ───────────────────────────────────────────────────────────────

output_cols = [
    "paper_arxiv_id", "paper_title", "repo_url", "framework",
    "year", "subfield", "conference", "is_official", "mentioned_in_paper"
]
corpus_out = corpus[output_cols].copy()
corpus_out["year"] = corpus_out["year"].astype(int)
corpus_out = corpus_out.reset_index(drop=True)

corpus_out.to_csv("corpus_1000.csv", index=False)
print(f"\n  Saved: corpus_1000.csv ({len(corpus_out)} papers)")

corpus_json = corpus_out.to_dict(orient="records")
with open("corpus_1000.json", "w") as f:
    json.dump(corpus_json, f, indent=2, default=str)
print(f"  Saved: corpus_1000.json")

# Save full methodology metadata for the paper
methodology = {
    "description": "Corpus selection methodology for ACM REP '26 benchmark",
    "source": "Papers with Code archive (final snapshot, July 2025)",
    "source_url": "https://huggingface.co/datasets/pwc-archive/links-between-paper-and-code",
    "license": "CC-BY-SA 4.0",
    "random_seed": RANDOM_SEED,
    "target_size": TARGET_N,
    "min_per_subfield": MIN_PER_SUBFIELD,
    "year_range": list(YEAR_RANGE),
    "inclusion_criteria": [
        "Has arXiv identifier",
        "Code hosted on GitHub",
        "Author-provided (official) repository link",
        f"Published {YEAR_RANGE[0]}-{YEAR_RANGE[1]}",
    ],
    "filtering_funnel": {
        "total_paper_code_links": total_links,
        "official_repos_only": n_official,
        "with_arxiv_id": n_arxiv,
        "github_hosted": n_github,
        "total_papers_in_archive": total_papers,
        "year_filtered": len(recent),
        "after_dedup": len(recent_dedup),
        "final_corpus": len(corpus_out),
    },
    "subfield_classification": "Keyword matching on PwC task annotations",
    "subfield_distribution": {sf: int(count) for sf, count in sf_dist.items()},
    "year_distribution": {str(int(yr)): int(count) for yr, count in year_dist.items()},
    "framework_distribution": {fw: int(count) for fw, count in fw_dist.items()},
    "allocation": {sf: int(n) for sf, n in allocation.items()},
}

with open("corpus_methodology.json", "w") as f:
    json.dump(methodology, f, indent=2)
print(f"  Saved: corpus_methodology.json")

print(f"\n{'=' * 60}")
print("DONE — ready for: replicant benchmark corpus_1000.csv")
print(f"{'=' * 60}")
