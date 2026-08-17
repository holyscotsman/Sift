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

Order matters: `build_canon_v2` → `build_canon_10k` → `patch_canon`. The other two
are checks, not steps.
