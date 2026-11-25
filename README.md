# MidMovieAds2026

Modular media discovery and broadcast timeline simulation for MidMovieAds-2026.

Current simulated inventory is stored in `source/test_data/media_inventory.json`. Choose `json` for simulated media metadata or `filesystem` for real files under `source/videos/`. Both modes use the same validators and then generate the timeline. Filesystem discovery reads durations with FFprobe, which must be available on `PATH`.

```powershell
python source/main.py --mode json
python source/main.py --mode filesystem
```

After a timeline has been generated and its referenced media files exist, render it into individual, serial-prefixed clips for VMix with:

```powershell
python source/rendering/ffmpeg_engine.py
```

The renderer uses the latest saved timeline by default. Pass `--timeline <path>` to choose one explicitly. Outputs are placed in a new folder under `source/videos/output/renders/`; source streams are copied without re-encoding, while timeline black intervals are generated as 1080p, 30 fps, silent MP4 clips.

For movie-and-ad-only testing, `source/config/settings.json` currently has all three `schedule_toggles` set to `false`. This skips the morning block, movie-gap song filler, and broadcast-ending song filler so a simulation can start at 09:00 with explicit empty gaps. Set the switches to `true` to restore those schedule blocks; when an individual switch is omitted, the application treats it as enabled.

To recover the expected media item and source seek position for the current
local system time, run the standalone recovery tool. It reads the newest saved
timeline directly and does not start the main application:

```powershell
python source/tools/recover.py
```

To inspect a particular timeline instead of the newest one:

```powershell
python source/tools/recover.py --timeline source/videos/output/timelines/timeline_YYYYMMDD_HHMMSS.json
```
