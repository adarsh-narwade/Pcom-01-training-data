#Column list of the PCOM-01 record schema, in the order of the shared sheet.
MONTHS = 12
SEVS = ["low", "moderate", "high", "critical", "unknown"]
M = range(MONTHS)

SERIES_METRICS = [
    "package_downloads", "package_download_days_observed", "package_stable_release_count",
    "issues_opened", "issues_closed", "issues_reopened",
    "pull_requests_opened", "pull_requests_closed_unmerged", "pull_requests_merged",
    "pull_requests_reopened", "issues_open_at_month_end", "pull_requests_open_at_month_end",
]
COLLECTED_SERIES = {"package_stable_release_count"}   # the rest stay NULL for now

META = ["purl", "package_created_at", "published_at"]
BASE = ["unpacked_size", "file_count", "dependency_count", "optional_dependency_count",
        "peer_dependency_count", "dev_dependency_count", "bundled_dependency_count"]
SERIES = [f"{m}_M{k}" for m in SERIES_METRICS for k in M]
GHSA = [f"ghsa_{s}_count" for s in SEVS]
GHSA_SERIES = [f"ghsa_{s}_count_M{k}" for s in SEVS for k in M]
TARGET = [f"target_ghsa_{s}_count_90d" for s in SEVS]

COLUMNS = META + BASE + SERIES + GHSA + GHSA_SERIES + TARGET
OPTIONAL = {"unpacked_size", "file_count"} | set(SERIES)
REQUIRED = [c for c in COLUMNS if c not in OPTIONAL]
TIMESTAMPS = {"package_created_at", "published_at"}
