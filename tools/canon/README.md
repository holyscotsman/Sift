# How `backend/sift/data/canon_10k.json` was built

Offline provenance scripts. **Nothing here runs at application runtime** — the app
only ever reads the finished JSON. They live in the repo so the data file has a
traceable origin rather than arriving as an opaque blob.

They need `numpy`, `pandas` and `scipy`, which are deliberately *not* project
dependencies; install them into a throwaway environment if you ever need to
rebuild. Set `CANON_WORK_DIR` to the directory holding the intermediate
artefacts (it defaults to the current directory).

| Script | Produces |
|---|---|
| `build_canon_v2.py` | The expanded candidate list from the source pillars |
| `build_canon_10k.py` | The final ten-thousand-title cut, with tiers |
| `patch_canon.py` | Targeted corrections against a built canon |
| `sweep_canons.py` | Cross-checks the result against the source lists |
| `build_similarity.py` | Item-item similarity from MovieLens 25M |
| `build_lists_from_imdb.py` | The 25,000-title canon and the exclusion list |

`build_lists_from_imdb.py` stands apart from the chain above. It takes the finished
ten-thousand-title canon as its floor — every entry keeps the tier and pillars it
earned there — and fills to twenty-five thousand from IMDb's official datasets,
while producing the exclusion list in the same pass. It needs **no** third-party
packages, only the standard library, and both inputs are public downloads:

```
curl -O https://datasets.imdbws.com/title.basics.tsv.gz
curl -O https://datasets.imdbws.com/title.ratings.tsv.gz
python tools/canon/build_lists_from_imdb.py \
    --basics title.basics.tsv.gz --ratings title.ratings.tsv.gz
```

It writes `canon_25k.json` and `exclude_list.json`, and never touches
`list_overrides.json` — hand corrections survive a rebuild by construction. See
`docs/RECOMMEND_LIST.md` and `docs/EXCLUDE_LIST.md`.

Order matters: `build_canon_v2` → `build_canon_10k` → `patch_canon`. The other two
are checks, not steps.
