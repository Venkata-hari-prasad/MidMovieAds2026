# Media discovery

`discover_media()` is the provider-neutral entry point. Choose the provider with `--mode json` or `--mode filesystem` when running the application.

Run from the repository root to validate the selected inventory and build its timeline:

```powershell
python source/main.py --mode json
python source/main.py --mode filesystem
```

Both modes return the same JSON-serializable normalized structure with a `source_type`, exact source metadata, and a `categories` mapping for `movies`, `dev-songs`, `movie-songs`, `songs`, and `ads`. Every category has an `exists` flag and path. Movie categories contain `folders`; each folder has a `folder_id`, its own `exists` flag, path, and `files`. Other categories contain `files`. Each file record has `filename`, `path`, `duration_seconds`, `category`, and `source_type`. JSON mode uses the simulated inventory's paths and durations without opening files. Filesystem mode enumerates real files under `videos/` and gets their durations with FFprobe; a file-specific probe failure leaves duration unknown for the shared validators to report. Missing categories and present-but-empty categories remain distinguishable.

The JSON provider loads `test_data/media_inventory.json` and does not require the simulated media paths to exist. The filesystem provider enumerates actual entries under `videos/`. Both modes pass their normalized inventory through the same movie, advertisement, and song validators before timeline generation. Filesystem mode requires `ffprobe` to be installed and available on `PATH`; no Python package dependency was added. FFmpeg rendering is not run by this command.

The provider parity demonstration can be run with `python source/test_data/demo_media_discovery.py`.
