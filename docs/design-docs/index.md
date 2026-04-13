# Design Docs Index

Catalog of design documents capturing architectural decisions and operating principles.

- `core-beliefs.md` -- agent-first and repository-legibility operating principles. Defines the foundational rules for knowledge management, configuration, versioning, and documentation structure.
- `acquisition-metadata-search-options.md` -- research-backed design study and five selective-index implementation plans for making OMERO.web acquisition metadata searchable.
- `python-acceleration-options.md` -- investigation of Cython, alternative runtimes/compilers, and strict acceleration rankings for this repository.

When adding a new design document:

1. Create the file in `docs/design-docs/`.
2. Add an entry to this index with a one-line description.
3. Cross-link from `docs/index.md` if the document introduces a new top-level concern.
