"""Command line of the report pipeline. Run from ``backend`` with ``PYTHONPATH=src``.

- ``python -m xai.cli.pipeline run --analysis <id>``: the report pipeline (what WatchOut starts);
- ``python -m xai.cli.k1 harvest-all --analysis <id>``: K1 only, every row of every event;
- ``python -m xai.cli.k1 harvest --analysis <id> --event <type> --row '<json>'``: one draft.

Exit codes: 0 done, 1 infrastructure error, 2 input error, 3 closing checks failed.
"""
