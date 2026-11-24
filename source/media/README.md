# Media discovery

`discover_media()` is the provider-neutral entry point. It reads the JSON application configuration from `config/settings.json`; that file currently contains an empty object because application settings have not yet been defined. Choose the provider explicitly with `discovery_mode` in a caller override or with the command-line demonstration. No discovery settings have been added to the config file.

Run from the repository root to display each provider's inventory:

```powershell
python source/main.py --mode json
python source/main.py --mode filesystem
```

Both modes return the same normalized structure with a `source_type`, exact source metadata, and a `categories` mapping for `movies`, `dev-songs`, `movie-songs`, `songs`, and `ads`. Every category has an `exists` flag and path. Movie categories contain `folders`; each folder has a `folder_id`, its own `exists` flag, path, and `files`. Other categories contain `files`. Each file record has `filename`, `path`, `duration_seconds`, `category`, and `source_type`. Filesystem durations are `null` because discovery does not probe media; simulated JSON durations are supplied by the inventory. Missing categories and present-but-empty categories remain distinguishable.

The JSON provider loads `test_data/media_inventory.json` and does not require the simulated media paths to exist. The filesystem provider enumerates actual entries under `videos/`. The terminal UI consumes normalized inventory only and identifies JSON data as simulated. Discovery does not apply validation rules and does not invoke FFprobe or FFmpeg.

The provider parity demonstration can be run with `python source/test_data/demo_media_discovery.py`.
