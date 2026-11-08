# Real sources of truth for the K4 tests

The seven sources of truth that K2 writes (format `0.2.0-k2`) for the
real detections, copied here unchanged after a pipeline run with `--force`:

| File | Detection |
|---|---|
| `handoff_ev_beffcb6f2a6e.json` | handoff, scene 21, condition A |
| `fight_ev_d966ffea748d.json`, `fight_ev_f55220f7838d.json` | fight, scene 5, condition A (two rows) |
| `vehicle_collision_ev_cb96ebb2235a.json` | vehicle_collision, scene 15, condition C, audio row |
| `vehicle_collision_ev_14cb6286bf2e.json`, `vehicle_collision_ev_e5fb52807ffa.json`, `vehicle_collision_ev_268dbbbc1515.json` | vehicle_collision, scene 15, condition C, visual rows |

From `backend`, for `gemini_3_6_flash_qwen2_audio_s5`, `_s21` and `_s15`:
`python -m xai.cli.pipeline run --analysis <id> --force`, then copy
`<out>/<analysis_id>/k2/<event>/<ev_id>.json` here as `<event>_<ev_id>.json`.

The tests that read this folder (`test_k4_view.py`, `test_k4_translation_translate.py`) are
skipped while it holds no `.json` file.
