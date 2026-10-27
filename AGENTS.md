# Public source repository

Edit overlays/ and integrations/ as the maintained source. .build/ contains generated upstream
workspaces and runtime files; do not commit it or treat changes there as maintained source.
Pinned upstream repositories and commits are in upstreams.json. Preserve their copyright notices.

Keep examples fictional. Never add credentials, real MACs, Wi-Fi data, personal personas,
recordings, transcripts, logs, Flash backups or downloaded model/resource binaries.
Run scripts/check_public.py and review the final Git diff before committing.

Use ESP-IDF 6.1 for firmware. Follow the pinned upstream board/build rules and scripts/build.py;
build one exact board variant at a time. Preserve network-origin checks, queue isolation,
deduplication, motion calibration and mechanical limits. Missing calibration must disable motion.

Run scripts/test.py in disposable unconfigured materialized workspaces. Report host tests,
firmware compilation and physical hardware validation separately. Do not claim historical
device acceptance applies to changed public sources. Do not contact Agents or cloud ASR
as part of an offline test unless the user explicitly authorizes it.

Update source-manifest.json hashes after deliberate source edits. Its entries describe the
distributable tree; they do not include itself, .git, .build or runtime/cache directories.
