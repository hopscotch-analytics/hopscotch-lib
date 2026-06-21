# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [Unreleased]

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
