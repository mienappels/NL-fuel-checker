# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### [0.3.0] - 2026-11-26

### Added

- Added ANWB as a supported fuel price source, with the ability to fetch and display prices from ANWB stations.

### [0.2.5] - 2026-11-26

### Fixed

- PompWijzer changed its API data format. Updated the integration to use the new versioned station and price snapshots, including stale-price filtering and consistent price/distance sorting.


### [0.2.4] - 2026-11-09

### Fixed

- Replaced the unsupported `async_timeout` dependency with the standard-library `asyncio.timeout`.


## [0.2.3] - 2026-10-21

### Changed

- Updated the integration version to 0.2.3.

### Fixed

- Fixed YAML platform startup by using the coordinator's standard refresh method instead of the config-entry-only first refresh.
- Platforms now report a failed initial data fetch as `PlatformNotReady`.

## [0.2.0] - 2026-10-08

### Changed

- Renamed the project from the old Independer-only integration to NL Fuel Checker.
- Updated the GitHub repository URL to the new project location.
- Added support for PompWijzer as an additional fuel price source alongside Independer.
- Updated documentation and configuration examples to reflect the new platform and supported sources.

### Added

- New `nl_fuel_checker` platform.
- Multi-source support for Dutch fuel price providers.

## [0.1.0] - 2026-10-08

### Added

- Initial release
- Support for fetching fuel prices from Independer.nl