#!/usr/bin/env python3
"""Item-item collaborative-filtering similarity from MovieLens 25M.

For every canon title present in ml-25m, the top-K most similar movies by
adjusted cosine over the user-rating matrix — i.e., "people who loved X also
loved Y", computed from 25M real ratings rather than metadata. Deterministic:
fixed dataset snapshot, no randomness, total ordering on ties.

Output: similarity_ml25m.json keyed by imdb id ("tt...") with top-K neighbor
[imdb_id, cosine] pairs, restricted to neighbors that are themselves canon
members (the app only ranks acquisition candidates, so off-canon neighbors are
noise it would re-filter anyway).
"""

import os

# Where the intermediate canon artefacts live. These are offline provenance
# scripts, run by hand outside the app, so the working directory is a parameter
# rather than a constant baked into the source.
WORK_DIR = os.environ.get("CANON_WORK_DIR", ".")


def work_path(name: str) -> str:
    return os.path.join(WORK_DIR, name)

import json, sys
import numpy as np
import pandas as pd
from scipy import sparse

K = 25
MIN_RATINGS = 300          # a movie needs this many ratings to have a stable vector

canon = json.load(open(work_path("canon_10k.json")))
canon_imdb = {t["imdb_id"] for t in canon["titles"] if "imdb_id" in t}
print(f"canon entries with imdb id: {len(canon_imdb)}", file=sys.stderr)

links = pd.read_csv("/tmp/ml-25m/links.csv", dtype={"movieId": "int32", "imdbId": "str"})
links["imdb"] = "tt" + links["imdbId"].str.zfill(7)
mid_to_imdb = dict(zip(links.movieId, links.imdb))

ratings = pd.read_csv("/tmp/ml-25m/ratings.csv",
                      usecols=["userId", "movieId", "rating"],
                      dtype={"userId": "int32", "movieId": "int32", "rating": "float32"})
print(f"ratings: {len(ratings):,}", file=sys.stderr)

counts = ratings.movieId.value_counts()
keep_mids = set(counts[counts >= MIN_RATINGS].index)
ratings = ratings[ratings.movieId.isin(keep_mids)]
print(f"movies with >= {MIN_RATINGS} ratings: {len(keep_mids):,}; ratings kept: {len(ratings):,}", file=sys.stderr)

# mean-center per user (adjusted cosine — corrects for generous/harsh raters)
user_mean = ratings.groupby("userId").rating.transform("mean")
ratings["adj"] = ratings.rating - user_mean

mids = np.array(sorted(keep_mids), dtype=np.int64)
mid_ix = {m: i for i, m in enumerate(mids)}
uids = ratings.userId.unique()
uid_ix = {u: i for i, u in enumerate(uids)}

M = sparse.csr_matrix(
    (ratings.adj.values,
     (ratings.movieId.map(mid_ix).values, ratings.userId.map(uid_ix).values)),
    shape=(len(mids), len(uids)), dtype=np.float32)
norms = np.sqrt(M.multiply(M).sum(axis=1)).A.ravel()
norms[norms == 0] = 1.0
print(f"matrix: {M.shape}, nnz {M.nnz:,}", file=sys.stderr)

canon_rows = [mid_ix[m] for m in mids if mid_to_imdb.get(m) in canon_imdb]
canon_row_set = set(canon_rows)
print(f"canon titles found in ml-25m with enough ratings: {len(canon_rows)}", file=sys.stderr)

out = {}
CHUNK = 400
canon_mask = np.zeros(len(mids), dtype=bool)
canon_mask[list(canon_row_set)] = True
for start in range(0, len(canon_rows), CHUNK):
    rows = canon_rows[start:start + CHUNK]
    block = M[rows]                              # (chunk, users)
    sims = (block @ M.T).toarray()               # (chunk, movies)
    sims /= norms[np.newaxis, :]
    sims /= norms[rows, np.newaxis]
    for local, r in enumerate(rows):
        s = sims[local]
        s[r] = -1.0                              # self
        s[~canon_mask] = -1.0                    # only canon neighbors
        top = np.argpartition(s, -K)[-K:]
        # total order: similarity desc, then movieId asc
        top = sorted(top.tolist(), key=lambda i: (-float(s[i]), int(mids[i])))
        src = mid_to_imdb[int(mids[r])]
        out[src] = [[mid_to_imdb[int(mids[i])], round(float(s[i]), 4)]
                    for i in top if s[i] > 0.02]
    print(f"  {min(start+CHUNK, len(canon_rows))}/{len(canon_rows)}", file=sys.stderr)

result = {
    "name": "similarity_ml25m",
    "version": "2026-08-14",
    "source": "MovieLens 25M (grouplens.org), F. Maxwell Harper and Joseph A. Konstan. Free for research/personal use with attribution.",
    "method": f"Adjusted-cosine item-item similarity over user ratings (per-user mean-centered). Movies with >= {MIN_RATINGS} ratings; top-{K} canon-member neighbors per title; ties broken by movieId. Deterministic.",
    "usage": "anchors = titles the household watched to completion; candidate score = sum of sim(anchor, candidate) over anchors; combine per ACQUISITION_ALGORITHM.md section 2.2b.",
    "count": len(out),
    "neighbors": out,
}
json.dump(result, open(work_path("similarity_ml25m.json"), "w"), ensure_ascii=False, separators=(",", ":"))
import os
print(f"wrote similarity_ml25m.json: {len(out)} titles, {os.path.getsize(work_path('similarity_ml25m.json'))//1024} KB", file=sys.stderr)
