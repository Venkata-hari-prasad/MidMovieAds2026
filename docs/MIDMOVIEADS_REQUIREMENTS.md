# MidMovieAds-2026 Requirements

> **Status:** Requirements baseline — V1 planning  
> **Scope:** Functional behavior, scheduling rules, constraints, validation, errors, and unresolved decisions.  
> **Timezone baseline:** `Asia/Kolkata` (proposed/configured default; see unresolved decisions).

## 1. Project overview

MidMovieAds-2026 is a Python and FFmpeg tool that reads media from four pools, builds one clock-aligned broadcast schedule, and renders that logical schedule as multiple sequential MP4 files. The operator points vMix at the generated files and plays them in numerical order, without arranging individual media by hand. The MP4s are consecutive physical parts of **one** schedule; they are not independent schedules and their cumulative clock does not reset at a file boundary.

| Pool | Purpose | Initial organization |
|---|---|---|
| `/movies` | Feature movies, processed in numbered movie groups | `m1`, `m2`, `m3`, … |
| `/dev-songs` | Devotional music for the morning window | Flat directories permitted |
| `/songs` | Regular songs, including flexible gap fill | Flat directories permitted |
| `/ads` | Complete advertisement plays between movie segments | Flat directories permitted |

The deliverables are numbered MP4 files, a human-readable cumulative timeline report, a generation summary, and generation logs. The timeline and every output file must preserve the same item order and durations.

### 1.1 How to read this baseline

Each requirement below has a stable ID, name, statement, and expected behavior. **Confirmed** identifies an agreed rule. **Proposed default** identifies an initial value that has not been fully approved. **TBD** means the rule is intentionally open and must not be silently inferred. The existing project directory contained no files at inspection time, so no current Python or FFmpeg segmentation behavior could be verified; this baseline therefore does not claim that existing behavior conforms.

## 2. Functional requirements

### 2.1 Media organization

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-MED-001 | Independent media pools | **Confirmed.** The system uses separate movie, devotional-song, regular-song, and advertisement pools. | Discover and classify media from `/movies`, `/dev-songs`, `/songs`, and `/ads` independently. |
| REQ-MED-002 | Numbered movie folders | **Confirmed.** Movies are grouped in explicitly numbered subdirectories named `m1`, `m2`, `m3`, and so on. | Treat each expected numbered directory as a movie group. |
| REQ-MED-003 | Numeric movie order | **Confirmed.** Movie playback follows numeric folder order. | Play `m2` after `m1` and before `m10`, regardless of filesystem enumeration or alphabetical filename sorting. |
| REQ-MED-004 | Movie folder contents | **Confirmed.** Each movie folder is expected to contain its corresponding movie media. | Validate folder presence and usable content before rendering. Exact rules for multiple media files per folder remain TBD. |
| REQ-MED-005 | Flat non-movie pools | **Confirmed.** Song and ad pools may initially be flat directory structures. | Discover eligible media in the configured pool without requiring numbered subfolders. |

### 2.2 Broadcast schedule and movie starts

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-SCH-001 | Broadcast day start | **Confirmed.** The logical schedule begins at 06:00 AM. | Use 06:00 as the morning schedule anchor, subject to startup padding/late-start rules. |
| REQ-SCH-002 | Devotional window | **Confirmed.** Devotional songs occupy 06:00–08:00 AM. | Schedule devotional content only within this window and stop at its boundary. |
| REQ-SCH-003 | Regular-song window | **Confirmed.** Regular movie songs occupy 08:00–09:00 AM. | Use regular songs in this window, including the available portion after a late start. |
| REQ-SCH-004 | First movie milestone | **Confirmed.** Movie 1 starts at 09:00 AM. | Preserve the 09:00 milestone when flexible startup content is shortened or skipped. |
| REQ-SCH-005 | Later movie milestones | **Confirmed.** Subsequent movie starts use configurable clock-time alignment rules. | Select eligible clock times according to configuration; do not infer an alignment from segment duration. |
| REQ-SCH-006 | Alignment choices | **Confirmed examples.** Supported configuration examples are `:00`, `:00 and :30`, and `:00, :15, :30, :45`. | Interpret these as eligible minute marks within each hour. The exact configuration syntax is TBD. |
| REQ-SCH-007 | Alignment independent of segment length | **Confirmed.** Movie-start alignment is independent of movie segment duration. | Calculate the next eligible clock start separately from segment boundaries. |
| REQ-SCH-008 | Configurable start tolerance | **Confirmed.** Movie-start tolerances are configurable. | Permit a start within configured timing tolerance as specified by the finalized scheduling rule. |
| REQ-SCH-009 | Independent early/late tolerance | **Confirmed.** Early and late tolerances are independently configurable. | Apply separate early and late limits; do not assume symmetry. Exact defaults and edge semantics are TBD. |

**Illustrative example (not a default):** with eligible starts at `:00` and `:30`, a movie segment and complete ad sequence that finish at 10:34 cannot make the 10:30 start. The scheduler evaluates the next eligible start, subject to configured tolerance, and fills the gap with regular songs. Exact eligibility/tolerance semantics remain TBD.

### 2.3 Movie processing

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-MOV-001 | Fixed-duration segmentation | **Confirmed.** Movies are divided into fixed-duration segments. | Produce consecutive segments that cover the movie according to the finalized remainder rule. |
| REQ-MOV-002 | Segment duration default | **Proposed default.** Segment duration initially defaults to 25 minutes. | Use 25 minutes only when no explicit valid value is configured; final policy is TBD. |
| REQ-MOV-003 | Configurable segment duration | **Confirmed.** Segment duration is configurable. | Validate configured duration before scheduling/rendering. |
| REQ-MOV-004 | No dynamic sizing in V1 | **Confirmed.** Dynamic segment sizing is not required for V1. | Do not resize segments dynamically to force movie starts. |
| REQ-MOV-005 | Reject abusive segment duration | **Confirmed.** Extremely small or otherwise abusive segment durations are invalid. | Stop before rendering with a fatal validation error when a configured value violates finalized limits. Exact bounds are TBD. |
| REQ-MOV-006 | Preserve movie content | **Confirmed.** Segmentation must not accidentally lose or duplicate movie content. | Segment ranges are consecutive and non-overlapping and collectively account for the source, subject to media timing precision. |
| REQ-MOV-007 | Preserve intended quality | **Confirmed.** Rendering should preserve intended video and audio quality. | Output quality must satisfy the eventual encoding/compatibility profile; exact profile is TBD. |
| REQ-MOV-008 | Minimum movie duration | **Confirmed rule; proposed value.** Each movie must meet a configurable minimum duration, initially proposed as 30 minutes. | Validate each movie against the configured minimum before rendering. The exact default is TBD. |

### 2.4 Advertisement processing

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-ADS-001 | Ads between segments | **Confirmed.** Advertisements are inserted between every movie segment. | Place an ad sequence after each movie segment, as defined by the configured sequence rules. Treatment after the final segment is TBD. |
| REQ-ADS-002 | Ad source pool | **Confirmed.** Ads are selected from `/ads`. | Do not substitute media from another pool. |
| REQ-ADS-003 | Ad ordering | **Confirmed.** Ad ordering is configurable as `random` or `given`. | `given` follows configured order; `random` uses a randomized order. Seed/reproducibility behavior is TBD. |
| REQ-ADS-004 | Ad repetition | **Confirmed.** Advertisement repetition is configurable. | Apply configured repetition semantics consistently; exact semantics are TBD. |
| REQ-ADS-005 | Fixed ad sequence | **Confirmed.** Ads play as a fixed sequence determined by configured order and repetition. | Complete the sequence as configured before evaluating a following movie start. |
| REQ-ADS-006 | No target-duration ad fitting | **Confirmed.** Ad insertion is not based on a target total duration. | Do not shorten or select ads merely to fit a desired ad-block duration. |
| REQ-ADS-007 | Ads play completely | **Confirmed.** Never truncate ads to satisfy a movie start time. | Render each selected ad to completion. |
| REQ-ADS-008 | Ad priority over immediate start | **Confirmed.** Ad playback takes priority over immediate movie-start alignment. | Finish the current configured ad sequence before evaluating the next eligible movie start. |
| REQ-ADS-009 | Evaluate after ads | **Confirmed.** Evaluate the next eligible movie start after the ad sequence completes. | Use the ad-completion timestamp as the input to start-time selection. |
| REQ-ADS-010 | Late tolerance after ads | **Confirmed; semantics TBD.** If the ad sequence finishes within allowed late tolerance, the movie may start then; if it exceeds tolerance, wait for the next eligible start. | Apply the configured late tolerance to the chosen eligible start. Boundary inclusivity and exact comparison anchor remain TBD. |
| REQ-ADS-011 | Fill post-ad gap | **Confirmed.** Regular songs fill remaining gaps after ads and before the subsequent movie start. | Select and truncate flexible songs only as permitted by song rules. |

### 2.5 Song processing

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-SON-001 | Regular song source | **Confirmed.** Regular songs come from `/songs`. | Do not source regular songs from the devotional pool. |
| REQ-SON-002 | Devotional song source | **Confirmed.** Devotional songs come from `/dev-songs`. | Do not source devotional songs from the regular-song pool. |
| REQ-SON-003 | Song ordering | **Confirmed.** Song ordering is configurable as `random` or `given`. | Follow configured order; exact random seed semantics are TBD. |
| REQ-SON-004 | Song repetition | **Confirmed.** Song repetition is configurable. | Apply configured repetition policy; exact semantics are TBD. |
| REQ-SON-005 | Devotional window restriction | **Confirmed.** Devotional songs are restricted to the dedicated morning window. | Do not schedule devotional songs outside 06:00–08:00. |
| REQ-SON-006 | Devotional boundary | **Confirmed.** Devotional playback stops at 08:00 AM. | Truncate a devotional song if needed at the boundary; do not cross into the regular-song window. |
| REQ-SON-007 | Regular-song morning window | **Confirmed.** Regular songs occupy 08:00–09:00 AM. | Use regular songs for that interval when available and eligible. |
| REQ-SON-008 | Songs are flexible content | **Confirmed.** Songs are flexible scheduling content. | Songs may be shortened, skipped, or used to fill a gap as the timing rules require. |
| REQ-SON-009 | Song truncation | **Confirmed.** Songs may be truncated to meet a scheduled transition or movie start. | Stop a song at the required boundary; report the actual played duration. |
| REQ-SON-010 | Final song completion not required | **Confirmed.** Completing the final song is not mandatory. | A final song may end at the schedule boundary without playing to completion. |
| REQ-SON-011 | Gap fill | **Confirmed.** Songs fill available gaps between ad sequences and subsequent movie starts. | Schedule eligible regular songs into such gaps, truncating where necessary. |
| REQ-SON-012 | Inventory sufficiency | **Confirmed.** Insufficient eligible song inventory is a fatal scheduling error. | Detect before rendering and stop if the required schedule cannot be filled. |
| REQ-SON-013 | Pre-render inventory validation | **Confirmed.** Song inventory sufficiency is validated before rendering. | Do not begin final rendering until validation passes. |
| REQ-SON-014 | Minimum inventory percentage | **Configurable; proposed threshold unconfirmed.** A minimum song inventory percentage may be configured; 20% is an example only. | Enforce only the configured threshold. Do not treat 20% as confirmed. Definition/denominator is TBD. |

### 2.6 Startup, transitions, and black video

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-TIME-001 | Early startup accommodation | **Confirmed.** Early operator startup may be accommodated with black-video padding. | If startup precedes 06:00 but is permitted, insert black video until the 06:00 devotional start. |
| REQ-TIME-002 | Earliest startup | **Proposed default.** The earliest allowed startup is initially 05:00 AM. | Reject an earlier start; exact configured boundary behavior is TBD. |
| REQ-TIME-003 | Pre-06:00 padding | **Confirmed.** For permitted startup before 06:00, insert black until the devotional window begins. | The logical playlist begins at operator startup and reaches 06:00 through black padding. |
| REQ-TIME-004 | Late startup uses flexible content | **Confirmed.** Late startup consumes flexible content without shifting critical movie milestones. | Skip unavailable flexible portions and retain scheduled milestones. |
| REQ-TIME-005 | Missed devotional content | **Confirmed.** Devotional songs that cannot be played because of late startup are skipped. | Do not extend devotional playback beyond 08:00 to recover missed time. |
| REQ-TIME-006 | Startup after devotional window | **Confirmed.** Startup after 08:00 skips devotional songs. | Start in the currently available schedule window. |
| REQ-TIME-007 | Late start before Movie 1 | **Confirmed.** Startup after 08:00 and before 09:00 uses available time for regular songs. | Fill only the remaining time to Movie 1's 09:00 milestone. |
| REQ-TIME-008 | Preserve first movie milestone | **Confirmed.** Movie 1 retains its 09:00 AM milestone. | Do not shift Movie 1 later to compensate for late startup. |
| REQ-TIME-009 | Latest startup limit | **Proposed upper boundary.** 09:00 AM is the proposed latest startup, subject to explicit boundary handling. | Reject startup beyond the finalized permitted latest time. Whether exactly 09:00 is allowed is TBD. |
| REQ-TIME-010 | Devotional-to-regular buffer | **Confirmed configurable buffer; proposed default.** A black-video buffer separates devotional songs from regular movie songs; proposed default is 20 seconds. | Insert the configured black interval at the transition to prevent an abrupt handoff. Exact placement relative to the 08:00 boundary must be specified in detailed scheduling rules. |
| REQ-TIME-011 | Black format compatibility | **Confirmed.** Black video is compatible with final playlist media and vMix playback configuration. | Generated black segments must meet the selected output media profile. Exact profile is TBD. |

### 2.7 Timeline integrity and validation

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-TLN-001 | Item timestamps | **Confirmed.** Calculate expected clock-time start and end for every scheduled item. | Report each planned item's cumulative start and end. |
| REQ-TLN-002 | Source traceability | **Confirmed.** Identify source filename and movie segment where applicable. | Each report entry maps to its original media and segment identity. |
| REQ-TLN-003 | Reflect actual flexibility | **Confirmed.** Timeline reflects truncated songs and complete advertisements. | Report actual scheduled song duration and full ad duration. |
| REQ-TLN-004 | Movie start reporting | **Confirmed.** Movie start timestamps are explicit. | Report each movie/segment start milestone. |
| REQ-TLN-005 | Verify rendered durations | **Confirmed.** Verify generated media durations. | Compare rendered item/file durations with planned values before declaring success. |
| REQ-TLN-006 | Validate final playlist | **Confirmed.** Check rendered playlist against the planned timeline. | Confirm sequence, durations, and cumulative boundaries. |
| REQ-TLN-007 | Rendering time independence | **Confirmed.** Generation duration does not alter intended playback schedule. | Schedule times derive from the intended playback timeline, not wall-clock rendering completion. |
| REQ-TLN-008 | Completion gate | **Confirmed.** Generation is complete only after rendering and output validation succeed. | Do not report a successful final playlist if either stage fails. |
| REQ-TLN-009 | Exact logical sequence | **Confirmed.** Output videos collectively preserve scheduled sequence without missing, duplicated, or reordered content. | Validate item continuity across files. |
| REQ-TLN-010 | Seamless file transitions | **Confirmed.** Consecutive files transition seamlessly in video and audio. | Boundaries must not create unintended gaps, overlaps, black flashes, or audio discontinuities. Quantitative tolerances are TBD. |
| REQ-TLN-011 | Cumulative timestamps | **Confirmed.** Timeline timestamps accumulate across all output files. | A new file continues the prior file's cumulative playback clock. |
| REQ-TLN-012 | Item-to-file mapping | **Confirmed.** Every scheduled item is traceable to its output video file. | Report the physical file containing each item, including items crossing a boundary if permitted. |

### 2.8 System-time verification

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-CLK-001 | Show system time | **Confirmed.** Before generation, display current system date, time, and timezone. | Present the observed values to the operator before rendering. |
| REQ-CLK-002 | Explicit confirmation | **Confirmed.** Operator explicitly confirms the system clock. | Do not proceed until confirmation is received. |
| REQ-CLK-003 | Timezone baseline | **Proposed/configured value.** Timezone is initially `Asia/Kolkata`. | Use the configured timezone for schedule calculations; treat other zones according to mismatch policy. |
| REQ-CLK-004 | Reject timezone mismatch | **Confirmed.** Unexpected timezone is fatal. | Stop generation if observed timezone does not match configured timezone. |
| REQ-CLK-005 | Record verified timestamp | **Confirmed.** Record verified system timestamp in generation log. | Include the confirmed timestamp and timezone in the run log. |

### 2.9 Operator deliverables and multiple files

| ID | Name | Status and requirement | Expected behavior |
|---|---|---|---|
| REQ-OUT-001 | Multiple MP4 deliverables | **Confirmed.** Primary output is multiple sequential video files. | Render the logical schedule into numbered MP4 parts. |
| REQ-OUT-002 | Zero-padded numbering | **Confirmed prefix pattern.** Files use zero-padded numerical prefixes such as `000_filename.mp4`, `001_filename.mp4`, and `002_filename.mp4`. | Number each part in playback order. Width is shown as three digits in the example; expansion rules are TBD. |
| REQ-OUT-003 | Numerical playback order | **Confirmed.** Files collectively form the complete schedule and play in numerical order. | Alphabetical sorting produces correct sequence. |
| REQ-OUT-004 | Unambiguous names | **Confirmed.** Naming prevents ambiguity in alphabetical sorting. | Use a consistent zero-padded numeric prefix and unique suffix. |
| REQ-OUT-005 | Human-readable timeline | **Confirmed.** A timeline report accompanies the videos. | Provide the fields in REQ-OUT-006. Report format is TBD. |
| REQ-OUT-006 | Timeline report fields | **Confirmed.** Report output filename, cumulative start/end, item duration, category, original filename, and movie segment where applicable. | Include these fields for each scheduled item and identify its containing output file. |
| REQ-OUT-007 | Generation summary | **Confirmed.** Summary shows total timeline duration, output file count, movie count, movie segment count, ad count, devotional song count, and regular song count. | Present counts and duration after validation. |
| REQ-OUT-008 | Troubleshooting logs | **Confirmed.** Generation logs are available. | Record relevant validation, timing, rendering, and output-validation results. |
| REQ-OUT-009 | No false success | **Confirmed.** Incomplete files are never presented as successfully generated final playlist files. | Mark failed/partial runs clearly and distinguish them from validated deliverables. |
| REQ-OUT-010 | One schedule across files | **Confirmed.** Multiple files are consecutive portions of one logical schedule. | Preserve one continuous order and cumulative timeline. |
| REQ-OUT-011 | No clock reset | **Confirmed.** Cumulative playback timestamps continue across file boundaries. | Do not restart the logical schedule clock at a new file. |
| REQ-OUT-012 | Safe file boundaries | **Confirmed.** Boundaries do not truncate or duplicate scheduled content accidentally. | Keep each item intact across boundaries unless explicit item splitting is allowed by finalized rules. |
| REQ-OUT-013 | Boundary rules unresolved | **TBD.** Rules dividing the schedule into MP4s are not finalized. | Do not infer fixed-duration or content-based splitting. |
| REQ-OUT-014 | Partial-run identification | **Confirmed future capability.** Identify files successfully generated if rendering fails partway through. | Report validated completed parts separately from incomplete/unvalidated parts. |
| REQ-OUT-015 | Per-file verification | **Confirmed.** Each output file should be independently checked for duration and media integrity. | Validate each part in addition to validating the complete sequence. |

## 3. Scheduling interpretation and constraints

The schedule has two distinct layers:

1. **Logical broadcast schedule:** the ordered items and their cumulative playback times, movie milestones, and fixed morning windows.
2. **Physical output files:** consecutive MP4 containers that hold portions of that same schedule. Their count, boundaries, and boundary policy remain TBD.

Advertisements are fixed-duration sequence content and always finish. Songs are flexible content and may be shortened or skipped to preserve fixed windows and eligible movie starts. Movie alignment is based on clock rules, not segment length. Movie content itself must not be lost or duplicated by segmentation. Exact tolerance comparisons, remainder treatment, and final-broadcast ending behavior remain open decisions.

## 4. Error catalogue

Codes are stable identifiers and must not be reassigned to different meanings. A warning or informational condition may be recorded without stopping generation; a fatal condition prevents successful final output. Where remediation is possible, the operator message should state the needed action.

| Code | Error name | Severity | Description and trigger condition | Expected behavior | Suggested operator message |
|---|---|---|---|---|---|
| E-MEDIA-001 | Missing media directory | FATAL | A required configured pool directory does not exist or cannot be found. | Stop discovery and generation. | `Required media directory was not found: {path}.` |
| E-MEDIA-002 | Empty required media directory | FATAL | A required pool has no eligible media after discovery. | Stop before rendering; report the pool. | `No eligible media was found in {path}.` |
| E-MEDIA-003 | Missing expected movie folder | FATAL | A numbered movie folder in the expected sequence, such as `m3`, is absent. | Stop movie schedule validation and identify the missing number. | `Expected movie folder m3 was not found in /movies.` |
| E-MEDIA-004 | Empty movie folder | FATAL | An expected movie folder contains no usable movie media. | Stop before rendering. | `Movie folder {folder} contains no usable media.` |
| E-MEDIA-005 | Invalid movie folder naming or numbering | FATAL | A movie directory name is malformed, duplicated, or violates the configured numbering sequence. | Stop and list offending names/sequence issue. | `Movie folder numbering is invalid: {details}.` |
| E-MEDIA-006 | Unsupported media format | FATAL | A discovered file format cannot be probed or rendered under the supported media profile. | Exclude only if exclusion still leaves a valid schedule; otherwise stop. V1 exclusion policy is TBD. | `Unsupported media format: {filename}.` |
| E-MEDIA-007 | Corrupt or unreadable media | FATAL | A source cannot be read or is corrupt during validation/probe. | Stop if required content is affected; identify source. | `Media file is unreadable or corrupt: {filename}.` |
| E-MOVIE-001 | Movie below minimum duration | FATAL | Movie duration is below the configured minimum. | Reject schedule before rendering. | `Movie {filename} is {actual}; minimum is {minimum}.` |
| E-MOVIE-002 | Movie shorter than segment duration | FATAL (policy TBD) | Movie is shorter than configured segment duration and short movies are prohibited by final rules. | Reject if prohibition is confirmed; otherwise apply finalized segmentation rule. | `Movie {filename} is shorter than one configured segment.` |
| E-MOVIE-003 | Invalid segment-duration configuration | FATAL | Segment duration is missing, malformed, below the safe minimum, or above permitted limits. | Stop configuration validation. | `Segment duration {value} is invalid; use a value within {limits}.` |
| E-ADS-001 | Empty advertisement pool | FATAL | No eligible ads exist while ad insertion is required between segments. | Stop before rendering; no silent omission. | `The advertisement pool is empty, but ads are required between movie segments.` |
| E-ADS-002 | Invalid advertisement repetition | FATAL | Repetition setting is malformed or incompatible with the sequence. | Stop configuration validation. | `Advertisement repetition setting is invalid: {value}.` |
| E-ADS-003 | Insufficient advertisements | FATAL (policy TBD) | Available ad inventory cannot satisfy finalized sequence/repetition rules. | Stop if the required sequence cannot be formed; exact shortage policy TBD. | `Advertisement inventory cannot satisfy the configured sequence.` |
| E-SONG-001 | Song exceeds maximum duration | FATAL | A song exceeds the configured maximum individual duration. | Reject offending source or schedule per finalized policy; do not silently truncate source during validation. | `Song {filename} exceeds the configured maximum of {maximum}.` |
| E-SONG-002 | Insufficient song inventory percentage | FATAL | Eligible song inventory percentage is below configured threshold. | Fail pre-render inventory validation. | `Eligible song inventory is {actual}%; configured minimum is {minimum}%.` |
| E-SONG-003 | Invalid song repetition | FATAL | Song repetition setting is malformed or incompatible with available inventory. | Stop configuration validation. | `Song repetition setting is invalid: {value}.` |
| E-SONG-004 | Insufficient eligible songs for gap | FATAL | Eligible songs cannot fill a required gap under configured rules. | Stop schedule construction before rendering. | `Not enough eligible songs to fill the gap ending at {time}.` |
| E-TIME-001 | System clock confirmation rejected | FATAL | Operator does not confirm the displayed system date/time/timezone. | Do not generate. | `System clock was not confirmed; generation was cancelled.` |
| E-TIME-002 | System timezone mismatch | FATAL | Observed timezone differs from configured timezone. | Stop before scheduling. | `System timezone is {actual}; expected {expected}.` |
| E-TIME-003 | Startup earlier than permitted | FATAL | Intended/observed startup precedes the configured earliest time. | Stop before rendering. | `Startup time {actual} is earlier than the permitted time {earliest}.` |
| E-TIME-004 | Startup later than permitted | FATAL | Startup is later than the configured latest boundary. | Stop before rendering. | `Startup time {actual} is later than the permitted time {latest}.` |
| E-TIME-005 | Invalid movie-start alignment | FATAL | Alignment configuration is malformed, empty, or contains invalid minute marks. | Stop configuration validation. | `Movie-start alignment is invalid: {value}.` |
| E-TIME-006 | Invalid early/late tolerance | FATAL | A tolerance is malformed, negative where prohibited, or inconsistent with alignment rules. | Stop configuration validation. | `Movie-start tolerance configuration is invalid: {details}.` |
| E-SCHEDULE-001 | Timeline cannot be constructed | FATAL | Scheduler cannot produce a valid ordered timeline satisfying fixed windows and constraints. | Stop before rendering and report the conflicting constraints if known. | `A valid schedule could not be constructed: {details}.` |
| E-SCHEDULE-002 | Invalid schedule boundary | FATAL | A planned item violates a fixed window, movie milestone, or allowed tolerance. | Reject timeline. | `Scheduled item {item} conflicts with boundary {boundary}.` |
| E-FFMPEG-001 | FFprobe metadata extraction failed | FATAL | FFprobe exits unsuccessfully or returns unusable metadata for required media. | Stop validation for affected source. | `FFprobe could not read media metadata for {filename}.` |
| E-FFMPEG-002 | FFmpeg executable unavailable | FATAL | FFmpeg cannot be located or launched. | Stop before rendering. | `FFmpeg is unavailable; check the configured executable path.` |
| E-FFMPEG-003 | FFmpeg rendering failed | FATAL | FFmpeg fails to render a required segment or output file. | Mark run incomplete; do not present final playlist as successful. | `FFmpeg failed while rendering {target}; see generation log.` |
| E-OUTPUT-001 | Missing intermediate segment | FATAL | A planned intermediate movie segment or rendered segment file is missing. | Fail final validation and identify the segment. | `Expected segment {segment} was not generated.` |
| E-OUTPUT-002 | Final output duration mismatch | FATAL | Aggregate rendered duration differs from planned logical duration beyond finalized tolerance. | Fail completion gate. | `Rendered playlist duration {actual} does not match planned duration {planned}.` |
| E-OUTPUT-003 | Output file missing or empty | FATAL | A planned MP4 is absent or has zero bytes. | Fail completion gate. | `Output file {filename} is missing or empty.` |
| E-OUTPUT-004 | Timeline report generation failed | FATAL | Required timeline report cannot be created or written. | Do not declare generation complete. | `Timeline report could not be generated: {details}.` |
| E-OUTPUT-005 | Insufficient disk space | FATAL | Available space is insufficient to safely complete planned rendering. | Stop before rendering where detectable; otherwise mark run incomplete. | `Insufficient disk space to render the planned playlist.` |
| E-OUTPUT-006 | Output validation failed | FATAL | A rendered output fails media integrity, sequence, duration, or playability validation. | Do not publish it as a final playlist. | `Output validation failed for {filename}: {details}.` |
| E-OUTPUT-007 | Missing or incorrectly numbered output | FATAL | Expected output is missing or numbering is duplicated, invalid, or out of sequence. | Fail playlist validation. | `Output numbering is incomplete or invalid: {details}.` |
| E-OUTPUT-008 | Gap or overlap between files | FATAL | Consecutive files have an unintended timeline gap/overlap or non-seamless boundary. | Fail playlist validation. | `Output boundary between {fileA} and {fileB} has a gap or overlap.` |
| E-OUTPUT-009 | Duplicate or missing content across boundary | FATAL | Comparison to the planned schedule finds an item duplicated or omitted across output boundaries. | Fail playlist validation. | `Playlist content mismatch at the boundary near {time}.` |
| E-OUTPUT-010 | Per-file duration mismatch | FATAL | An individual output duration differs from its planned duration. | Fail file and playlist validation. | `Output {filename} duration {actual} differs from planned {planned}.` |
| E-OUTPUT-011 | Partial output from failed run | WARNING | Rendering failed after some files were produced and some completed files pass independent validation. | Identify validated parts as partial-run artifacts; never label the playlist complete. | `Generation stopped early; {count} validated part(s) are available, but the playlist is incomplete.` |
| E-CONFIG-001 | Invalid configuration value | FATAL | A required setting is missing, malformed, or outside its finalized allowed values. | Report key and expected form; stop before rendering. | `Configuration value {key} is invalid: {details}.` |
| E-CONFIG-002 | Conflicting configuration | FATAL | Two settings cannot both be satisfied, such as incompatible windows/tolerances. | Stop and identify conflicting settings. | `Configuration settings conflict: {details}.` |

**Severity note:** The catalogue uses fatal behavior when the requested complete playlist cannot be validated as safe and complete. Unsupported/corrupt media exclusion could become a warning only if a future explicit policy permits skipping it and the resulting schedule remains valid. No such skip policy is confirmed here. Error codes, once adopted, remain stable even if message wording changes.

## 5. Unresolved decisions (TBD)

These choices remain open and must not be silently resolved by implementation or by this document.

| TBD ID | Decision | Current note |
|---|---|---|
| TBD-001 | Minimum and maximum segment durations | Exact safe bounds are not set. |
| TBD-002 | Default minimum movie duration | 30 minutes is initially proposed, not finalized. |
| TBD-003 | Song inventory percentage | 20% is an example only; threshold and denominator are unconfirmed. |
| TBD-004 | Maximum individual song duration | No value is set. |
| TBD-005 | Latest startup boundary | 09:00 AM is proposed; inclusive/exclusive behavior is unsettled. |
| TBD-006 | Playback start timestamp source | Decide whether operator supplies the intended timestamp or tool derives it from current system time. |
| TBD-007 | Early/late tolerance defaults | Values and exact comparison semantics are not set. |
| TBD-008 | Ad selection reset | Decide whether ad sequence resets after each movie segment or continues across the broadcast. |
| TBD-009 | Ad repetition semantics | Define what count/repeat means and whether sequence restarts per segment. |
| TBD-010 | Song repetition semantics | Define repeat limits, reset behavior, and whether a song may repeat within a window. |
| TBD-011 | Short final movie segment | Define how a movie remainder shorter than the configured segment duration is handled. |
| TBD-012 | Final movie and remaining time | Define whether ads/songs follow the last movie segment and when the broadcast schedule ends. |
| TBD-013 | Media compatibility profile | Specify codecs, resolution, frame rate, audio format, and vMix compatibility requirements. |
| TBD-014 | Output structure and full naming | Specify directory layout and suffix format beyond the numeric prefix. |
| TBD-015 | Insufficient advertisements | Define whether shortage is fatal in all configurations, whether fewer ads can be used, and how this interacts with fixed sequences. |
| TBD-016 | Unreachable eligible movie start | Define exact behavior when tolerances cannot reach a start, including wait/skip/error policy. |
| TBD-017 | Output file division rules | Specify how one logical schedule is split into files. |
| TBD-018 | Output boundary policy | Decide whether boundaries follow movie boundaries, fixed durations, or another configurable rule. |
| TBD-019 | Recovery after partial rendering | Decide whether individual files can be independently regenerated and how resume is validated. |
| TBD-020 | Encoding consistency | Decide whether all output videos must use identical encoding parameters. |
| TBD-021 | Independent playability | Decide whether each file must play standalone without preceding files. |
| TBD-022 | Startup timestamp and clock relationship | Define whether a late-start timestamp is sampled once, confirmed manually, or otherwise held stable for the schedule. |
| TBD-023 | 08:00 transition buffer placement | Define whether 20-second black is inside the devotional window, between windows, or included in the regular-song hour. |
| TBD-024 | Multiple files per movie folder | Define whether each `mN` contains one file, multiple parts to concatenate, or other media. |
| TBD-025 | Random selection reproducibility | Define seed handling and whether selected sequences are recorded for repeatable runs. |
| TBD-026 | Duration/timebase tolerances | Define acceptable measurement error for item, file, cumulative, and seam durations. |
| TBD-027 | Ad sequence after final segment | Clarify whether the between-segment rule implies no ad sequence after the last segment. |
| TBD-028 | Movie segment scheduling relationship | Clarify whether each segment is a distinct movie-start milestone for alignment or only subsequent full movies align. |

## 6. Ambiguities and consistency checks

1. **What counts as a movie start:** Movie segmentation is fixed-duration and ads follow every segment, while the schedule describes starts for Movie 1 and subsequent movies. It remains unclear whether each segment of one movie is itself aligned to a movie-start grid or whether alignment applies only between movie titles. See TBD-028.
2. **Clock time versus cumulative playback time:** A confirmed clock-time schedule and operator startup time imply a mapping from wall clock to playlist playback. The source and sampling rules for that mapping are open (TBD-006, TBD-022).
3. **08:00 buffer placement:** A 20-second black transition is required while the devotional window ends at 08:00 and the regular-song window begins at 08:00. The placement could affect the defined window duration, so it must be settled (TBD-023).
4. **Startup exactly at 09:00:** This is expressly not resolved by the proposed latest boundary (TBD-005).
5. **Movie folder cardinality and missing numbering:** A gap such as absent `m3` is listed as an error, but the expected final movie number and whether folders beyond a gap are valid need a manifest or configured count (TBD-024 plus configuration definition).
6. **Advertisement requirement versus empty/insufficient pool:** Ads are required between segments, but exact sequence and repetition semantics and whether an empty pool can ever be allowed are open (TBD-008, TBD-009, TBD-015).
7. **Output boundaries versus item traceability:** Files should not truncate/duplicate content and every item must map to a file, while standalone playability and item splitting are undecided (TBD-017–TBD-021).
8. **Duration conservation:** Movie content must be preserved, but exact media timebase tolerance, frame-boundary rounding, and whether source timestamps can be discontinuous are unspecified (TBD-026).
9. **Final schedule extent:** No broadcast end time or final-item policy is defined (TBD-011, TBD-012).

**Consistency review:** All 95 numbered decisions from the brief are represented by the requirement IDs in Sections 2 and 3; the schedule layer and file-division layer are explicitly distinguished. Proposed 25-minute segments, 30-minute minimum movie duration, 05:00 earliest startup, 09:00 latest startup, 20-second transition buffer, `Asia/Kolkata`, and example 20% song threshold are labeled proposed/configured rather than silently treated as finalized defaults. Every catalogue entry has a unique `E-<CATEGORY>-<NUMBER>` code. No source behavior was verified because the inspected project directory was empty.

## 7. Important missing requirements to decide later

The supplied decisions do not yet define the broadcast end condition, source-file selection rules when folders contain multiple files, media exclusions and warnings, random-sequence reproducibility, measurable seamlessness/duration tolerances, output directory layout, restart/resume behavior, or how operator-supplied startup time is reconciled with the verified system clock. These omissions are captured as TBD items where applicable; they are not assumed product requirements in this baseline.
