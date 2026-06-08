# DataSure

Automated QA/testing tool for data/analytics applications - a QSDA Pro alternative.

## Overview
DataSure is an automated QA/testing tool for data/analytics applications, designed to address limitations of existing tools like QSDA Pro while avoiding copyright issues through clean-room implementation. It focuses on validating data models, reports, dashboards, and ETL processes across multiple platforms (Qlik Sense, Tableau, Power BI, custom applications).

## Key Features
- Open-source core with optional enterprise extensions
- No object limits in free tier
- Support for personal/user-specific sheets and remote server access
- Built-in connectors for major analytics platforms
- Custom validation engine (not reliant on platform-specific syntax checkers)
- Business logic validation, UI/UX checks, performance benchmarking
- Cross-platform support with plugin architecture

## Project Structure
```
src/
├── core/                 # Main validation orchestration and plugin management
├── connectors/           # Platform-specific connectors (Qlik Sense, Tableau, Power BI)
├── validators/           # Validation engines (business logic, data quality, etc.)
├── config/               # Configuration management
├── reporting/            # Test report generation
└── tests/                # Unit and integration tests
```

## Installation
```bash
pip install -e .
```

## Usage
```bash
datasure validate --app-id <app_id> --platform qlik
```

## Development
See CONTRIBUTING.md for development guidelines.

## License
MIT License