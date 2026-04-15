# Prompts Directory Cleanup

Mechanical file-organization tasks. Do these when convenient; they don't gate any launch work.

## Move to completed/ (already implemented or nearly so)
- [X] quick-stats-freshness.md — ~90% wired, props exist in GameReportClient.tsx
- [-] precompute-detail-and-dashboard-queries.md — moved to completed/, broken into 3 focused prompts:
  - [X] precompute-wire-trend-matviews.md — rewrite 8 trend methods to read from existing matviews
  - [X] precompute-denormalize-ea-reviews.md — add has_early_access_reviews to games, remove reviews scan
  - [ ] precompute-game-metrics-cache.md — cache detail-page review metrics (low priority)
- [ ] revenue-estimator-v2.md — partially done, fields exist, algorithm refinement remains

## Move to notes/ or doc/ (not implementation specs)
- [ ] product-ideas.md — running brainstorm, explicitly "NOT a roadmap"
- [ ] data-intelligence-features.md — feature roadmap brainstorm
- [ ] landing-page-positioning.md — messaging/positioning strategy doc
- [ ] value-assessment.md — Claude Code analysis prompt, not a feature

## Revise or rewrite
- [ ] prompt-eval-pipeline.md — stale, assumes pre-data-source-clarity GameReport shape
