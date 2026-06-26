# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [Unreleased]

## [0.5.1] - 2026-06-26

### Changed
- **Step Matrix sort icons** — anchor column header now shows sort icons; event rows sort lexicographically

## [0.4.0] - 2026-06-24

### Added
- **Step Matrix widget** (`es.step_matrix()`) — interactive heatmap table showing step-by-step transition probabilities. Features: multi-block horizontal layout with serrated separators, resizable first column, sticky header, drag-and-drop row reordering, hidden events section, diff mode with per-group event counts, cell tooltips, "Go to" / "Search event" dropdown, path_pattern input with Apply button, global heatmap normalization across blocks, cloud save/load
- **`Eventstream.fingerprint`** — cached content-based hash (MD5 of schema + event counts + shape) for detecting eventstream compatibility when loading cloud state
- **`CloudMixin`** — reusable mixin (`src/hopscotch/widgets/cloud_mixin.py`) extracting all cloud save/load logic shared between widgets; new widgets can inherit it to get cloud support for free
- **`_utils.py`** — shared `parse_diff()` helper extracted from widget modules
- **`widget-utils.tsx`** — shared JS utilities: `parseJson`, `ComputingSpinner`, `HsSpinKeyframes` extracted from all widget files
- **Cloud overwrite confirmation** — saving to an existing file name now shows a confirmation dialog
- **Cloud error modal** — "File not found" and other cloud errors shown as dismissible modal instead of small badge
- **Cloud state compatibility warning** — yellow banner when loaded state was saved for a different eventstream; auto-save disabled in this case to protect the saved file
- **Auth continuation** — after authenticating, the action that triggered auth (e.g. opening save dialog) is automatically resumed
- **Auto-save for Step Matrix** — when widget is loaded from cloud, display state changes auto-save after 1.5s debounce
- **`isDirty` Apply buttons** — Apply button in segment_overview and cluster_analysis now appears (yellow) only when settings have changed; hidden otherwise
- **No-data overlay** — Transition Graph shows "Loading…" / "No data" overlays when cloud_file_name is set but data not yet loaded
- **"Search event" button** in Step Matrix header (renamed from "Go to…", styled to match Transition Graph)

### Changed
- **`edge_weight` parameter rename** — `transition_graph(values=...)` → `transition_graph(edge_weight=...)` and `transition_graph_data(values=...)` → `transition_graph_data(edge_weight=...)` for consistency
- **Cloud save modal** redesigned as centered dialog with description note that only widget configuration is saved (not eventstream data)
- **Filled pin icon** when active — pin icon fills with yellow color when pinned (same across Step Matrix and Transition Graph search dropdown)
- **`CloudMixin` refactor** — `StepMatrixWidget` and `TransitionGraphWidget` now inherit shared cloud logic; cloud_file_name deferred recompute when file is set
- **Save type names** standardised to Title Case: `"Step Matrix"` and `"Transition Graph"`
- **Cluster Analysis tabs** layout fixed — Overview/Silhouette tabs now correctly appear above the content
- Widget-level **`_parse_diff`** functions consolidated into `widgets/_utils.py`

### Fixed
- **SQL injection** in `funnel.py` — event names in DuckDB queries now properly escaped with single-quote doubling
- **`asdict()` vs `__dict__`** — `collapse_events()` now uses `asdict(new_schema)` consistently with all other data processors
- **Race condition** in `_schedule_cloud_save()` — timer is created and started before assigning to `self._cloud_save_timer`
- **Cloud HTTP errors** now propagate as `RuntimeError` with descriptive message instead of being silently swallowed
- **Schema validation** — `EventstreamSchema.__post_init__` now raises `ValueError` for empty `path_cols`/`event_cols` and duplicate column names
- **HDBSCAN `copy` FutureWarning** — `copy=True` now explicitly passed
- **Step Matrix ORDER BY** — paths query in `_process_pattern_matrix` now includes `ORDER BY` to ensure correct event sequence for center-position lookup
- **Step Matrix block layout** — blocks now display horizontally (side by side) with serrated separators; subsequent blocks share rows with block 1
- **Transition Graph edge_weight** — JS traitlet properly synced to renamed `edge_weight` key (was reading stale `values` key)
- **`segment_overview` Apply button** — fixed `isDirty` ReferenceError (prop was used in `Sidebar` component but not declared)
- Auto-save and recompute are now **blocked until initial cloud load completes** to prevent overwriting saved state with defaults on invalid `cloud_file_name`

## [0.3.6] - 2026-06-23

### Changed
- `Eventstream` converted from dataclass to regular class; constructor parameters renamed `_df` → `df`, `_schema` → `schema`
- `step_window` default changed from `0` to `3` in `step_sankey()`

### Fixed
- `sidebar_open` parameter added to `funnel()`, `segment_overview()`, `cluster_analysis()` wrappers

## [0.3.5] - 2026-06-22

### Added
- Public README

### Changed
- API renames: `values` → `edge_weight` in `transition_graph()`, `values` → `by_column` in `filter_events()`, `object_name` → `cloud_file_name` in `transition_graph()`, `metrics` → `features` in `add_clusters()`
- `load_from` parameter removed from all widget factory methods

## [0.3.4] - 2026-06-21

### Added
- "Manage saved widgets" link in cloud section — opens widget management page on the platform

### Fixed
- Auth overlay can now be closed with × button or Escape
- Stable AuthGate DOM structure prevents Cytoscape from re-laying out nodes when overlay is toggled

## [0.3.3] - 2026-06-21

### Added
- Cloud save/load for Transition Graph widget — save node positions, params and event visibility to Supabase; invite-only early access
- `step_window` parameter added to `es.step_sankey()`
- Cluster Analysis auto-computes on init when `features` are explicitly provided

### Changed
- Headless methods renamed to match widget names: `transition_graph_data`, `step_sankey_data`, `funnel_data`, `segment_overview_data`, `cluster_analysis_data`
- Removed `paywall_required` traitlet and 1000-path limit from all widgets
- Local widget state persistence (`object_name`, `load_from`) removed from all widgets except Transition Graph (cloud only)
- `path_start` / `path_end` events can now be hidden and pinned in Search event panel

### Fixed
- JWT expiry check in `loadSession()` now decodes the actual token expiry
- Token refresh via `refreshSession()` using Supabase refresh token
- `path_start` / `path_end` event counts now correct in diff mode
- StepSankey diff tooltip switched to light theme
- Spinner colours unified to `--hs-yellow` CSS variable
- Leftover `_save_path` references removed from cluster_analysis, segment_overview, step_sankey

## [0.3.2] - 2026-06-21

### Added
- `ipywidgets` added as a core dependency for out-of-the-box JupyterLab support
- `paywall_required` traitlet added to all widgets (infrastructure for future freemium)

## [0.3.1] - 2026-06-21

### Fixed
- `_get_esm()`: use correct package name `hopscotch-analytics` for version
  lookup; fallback to `"latest"` caused 404 when downloading widget.js
- `_get_esm()`: cache downloaded widget.js to disk so subsequent imports
  don't re-download the bundle on every use

## [0.3.0] - 2026-06-21

### Added — Cluster Analysis
- **`ClusterAnalysis` tool**: KMeans and HDBSCAN clustering with optional NMF
  decomposition; supports `n_clusters` / `nmf_k` as single value, range
  (`"3-8"`), or comma-separated list (`"3,5,7"`) for silhouette grid search
- **`ClusterAnalysisWidget`** (anywidget): interactive sidebar with Configure
  Features, Configure Metrics, clustering method, scaler, N Clusters, NMF
  Decomposition fields; heatmap overview, silhouette chart, NMF H/W matrices
- **Silhouette grid search**: selects best parameter set automatically and
  highlights it in the bar chart

### Added — Segment Overview
- **`segment_levels` traitlet**: segment column values available in
  Configure Metrics `belongs_to` fields without extra round-trips
- **`active_days` event selector** in Configure Metrics and Configure
  Features: optional filter to count only days with specific events

### Added — shared metric form components
- `metric_config_row.tsx`: unified `MetricRow`, `MultiSelect`, `SingleSelect`,
  `InfoTip`, `validateMetricCfg` shared across Configure Features (CA),
  Configure Metrics (CA), and Configure Metrics (SO) — ~650 lines removed
- `showAgg=false` for Configure Features (no aggregation dropdown)
- All three forms default new rows to `event_count` with all events selected
- InfoTip on Cluster Analysis sidebar Metrics label explaining overview metrics

### Changed
- Package renamed from `hopscotch` to `hopscotch-analytics` on PyPI
- Aggregation global dropdown removed from Cluster Analysis sidebar;
  aggregation is now configured per-metric in Configure Metrics

### Fixed — Segment Overview
- `segLevels` ReferenceError crash in metrics overlay
- `SidebarSH` inline component causing remount and focus loss on
  Configure Metrics open

### Fixed — Cluster Analysis
- Default `n_clusters=""` causing KMeans to fail on widget init; now
  defaults to `"3-8"`
- NMF K text field losing focus on each keystroke

## [0.2.2] - 2026-06-19

### Fixed
- `_get_esm()`: fetch widget.js source and return as string to anywidget
  (anywidget requires inline JS string, not a URL)

## [0.2.1] - 2026-06-19

### Fixed
- `_get_esm()`: download widget.js to local cache instead of passing URL
  to anywidget directly

## [0.2.0] - 2026-06-19


### Added — Transition Graph
- **Diff mode node coloring**: nodes tinted red/blue based on event share
  difference between groups; inner circle radius shrinks proportionally
  to diff magnitude (zero diff = normal donut, max diff = solid circle)
- **Node hover tooltip** in diff mode: shows share breakdown per group
  with subtitle "share of event in group"
- **Colored dots** (● blue / ● red) next to segment value dropdowns so
  it's immediately clear which color maps to which group
- **Fit to canvas** button (expand icon, top-right toolbar) replaces the
  old Reset Layout button; calls `cy.fit` with 12 px padding
- **Auto-fit on load**: graph fits the canvas automatically on every
  render (both auto-layout and saved-positions paths)
- **Edge Weight Type** label (renamed from "Value Type") in settings sidebar

### Fixed — Transition Graph
- `value1Label` / `value2Label` falling back to "group1"/"group2" when
  diff values are boolean `false` — now uses `String()` coercion
- Diff tooltip label now correctly shows the actual segment value

### Added — Step Sankey
- **`step_window` parameter**: frontend-only slider in sidebar Visibility
  Settings (Radix single-thumb slider, amber track); defaults to 3;
  limits displayed columns per anchor without recomputing backend data
- **Event Count filter**: sidebar RangeSlider now populated with real
  `COUNT(DISTINCT path_id)` per event from Python backend;
  `_populationCustomized` flag prevents reset on recompute
- **Pattern edit menu** matching platform UX: path_start/path_end show
  insert panel directly; internal events show Insert Before / Insert
  After / Replace / Delete first-level menu with Event / Gap+Event tabs
- `path_start` and `path_end` included in all event dropdowns
- Diff tooltip label fix (same boolean coercion fix as transition graph)

### Fixed — Step Sankey
- **Gap+Event for `path_end`** now inserts `event->.*->path_end`
  (own matrix block) instead of collapsing with existing wildcard
- **`PatternStore`**: `addWithTrailingGap` method; default display
  pattern (`path_start->.*->path_end`) no longer leaks into edit state
  when no real pattern is set — adding events from path_start no longer
  appends path_end
- **Column filtering**: end-aligned and start-aligned matrices now
  correctly limit variable columns on both sides by `stepWindow`
- **`path_start`/`path_end`** excluded from regular column event nodes
  (appear only as fixed anchors)
- **`_find_center_position`**: regex split handles leading/trailing `.*`
  wildcards — fixes `PatternNoMatchError` for `.*->path_end` patterns
- **Diff mode** with `.*->path_end`: `original_pattern` passed to sub-
  calls so `skip_first_matrix` applies correctly in each group
- **`path_start->.*->path_end`** default no longer shown as a third
  matrix block when user adds a central event via GUI

### Fixed — Python widget
- **Save initial widget state** on creation with `object_name` —
  state is now written synchronously so a subsequent load always
  restores `path_pattern`, `diff`, etc.

## [0.1.0] - 2026-06-17

### Added
- `Eventstream` class with DuckDB-powered step matrix and transition matrix
- `StepSankeyWidget` (anywidget): interactive step sankey with pattern editing,
  diff mode, segment filters, `max_steps`, persistence via `object_name`
- `TransitionGraphWidget` (anywidget): Cytoscape.js force-directed graph,
  edge weight types, diff mode, event count filter, node/edge color picker
- Supabase OTP authentication paywall baked into bundle at build time
- GitHub Actions release pipeline: builds JS bundle, creates GitHub Release
  with `widget.js` asset, syncs Python history to public repo via
  `git filter-repo`
