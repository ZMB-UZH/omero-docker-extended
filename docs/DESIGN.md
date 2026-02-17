# Design Principles

- Prefer explicit contracts for configuration, startup order, and service dependencies.
- Keep plugin logic modular with clear separation between request handling, orchestration, and external service calls.
- Preserve deterministic behavior across environments by requiring explicit environment variables.
