# Python Acceleration Options Investigation

Investigation conducted on 2026-04-12 for the repository-wide question of
whether the Python-heavy portions of this codebase can be accelerated through
fully automatic conversion, Cython, or another runtime/compiler approach.
Repository file counts were refreshed on 2026-07-18.

## Goal

Answer four architecture questions before any implementation work:

1. Can all Python code be converted automatically with zero side effects?
2. Can Cython provide a fully automatic and bug-free path to dramatic speedups?
3. Is there another language or compiler that can do this automatically?
4. What is the strict ranking of realistic acceleration strategies for this
   repository?

## Executive summary

- No current toolchain provides all three of these properties for arbitrary
  Python code: fully automatic conversion, bug-free behavior preservation, and
  dramatic speedups.
- Cython can automate compilation, but large gains come from selectively typing
  hot code paths. That is not the same as zero-risk whole-repo conversion.
- Benchmark articles that report `6x`, `10x`, or `100x` speedups are usually
  measuring CPU-bound numeric loops, not Django views, OMERO API calls,
  filesystem work, subprocess orchestration, or network-bound request paths.
- For this repository, the most realistic performance wins are more likely to
  come from profiling, reducing OMERO round trips, reducing filesystem scans,
  batching work, and isolating the small number of CPU-heavy helper functions
  before considering compiled acceleration.
- No implementation is planned from this investigation alone.

## Repository-specific findings

### Python footprint

- Production Python files: `158`
- Production Python lines: `82,620`
- Test Python files: `186`
- Test Python lines: `134,583`

Most tracked Python in the repository is test code, so any "convert all Python"
strategy would mostly compile tests unless the build is carefully filtered.

### Largest production modules inspected

- `omero_imaris_connector/XTOmeroConnector.py`: `15,358` lines
- `omeroweb_import/views/core_functions.py`: `10,223` lines
- `omeroweb_admin_tools/views/index_view.py`: `3,592` lines
- `tools/cocoindex_agent_search.py`: `3,114` lines
- `omeroweb_import/views/index_view.py`: `1,888` lines
- `omero_web_zarr/integration.py`: `1,808` lines
- `omeroweb_tools/services/enhanced_search_service.py`: `1,687` lines
- `omeroweb_import/services/ome_zarr_support.py`: `1,669` lines
- `omero_web_zarr/utils.py`: `1,556` lines
- `omeroweb_tools/services/acquisition_metadata.py`: `1,468` lines
- `tools/regression_guard.py`: `1,428` lines
- `omeroweb_tools/services/enhanced_search_store.py`: `1,422` lines
- `omeroweb_admin_tools/services/log_query.py`: `1,375` lines
- `omero_imaris_connector/imaris_service.py`: `1,353` lines
- `omero_imaris_connector/views.py`: `1,335` lines
- `tools/env_safety_guard.py`: `1,270` lines
- `omeroweb_import/services/omero/sem_edx_parser.py`: `1,245` lines
- `omero_web_zarr/views.py`: `1,287` lines
- `omeroweb_omp_plugin/views/index_view.py`: `1,216` lines
- `omero_imaris_connector/omero_scripts/IMS_Export.py`: `1,171` lines

### Dominant runtime patterns

The largest production modules are not dominated by numeric kernels. They are
primarily composed of:

- OMERO API access and object traversal
- filesystem path handling, JSON reads/writes, and directory scans
- subprocess launch and process supervision
- HTTP request/response handling
- lock management and job-state persistence
- integration glue across Django, OMERO, Zarr, and Celery surfaces

That matters because compiled acceleration helps most when runtime is spent in
tight CPU-bound loops over predictable data structures.

### Build and deployment constraints

The current deployment model copies Python packages directly into container
site-packages and already depends on native-extension build tooling for some
dependencies:

- `docker/omero-web.Dockerfile`
- `docker/omero-celery-worker.Dockerfile`

The OMERO.web image explicitly documents native build requirements for
`omero-py` and ZeroC Ice. Any additional compiled-extension strategy would add
another layer of ABI, wheel, compiler, and runtime-compatibility maintenance.

## Cython findings

### Current upstream state

The latest stable Cython release checked during this investigation was
`3.2.4`, published on `2026-01-04`.

Primary upstream sources reviewed:

- GitHub releases
- official Cython tutorials and user guide
- packaging guidance for binary extensions
- community discussions and write-ups about real-world Cython adoption

### What Cython can do automatically

- Compile many existing Python modules with little or no source change
- Generate CPython extension modules from `.py` or `.pyx` inputs
- Deliver modest speedups in some cases even without manual typing

### What Cython cannot guarantee automatically

- identical behavior for every dynamic Python feature and every dependency
- dramatic speedups for I/O-bound or integration-heavy code
- zero maintenance overhead
- zero debugging complexity

The larger Cython gains in the reviewed examples come after adding explicit
C-level types, narrowing data structures, or relaxing runtime safety checks.
That is selective optimization, not transparent whole-repo conversion.

### Why whole-repo automatic Cythonization is not zero-risk

- Plain compilation alone usually produces modest gains, not benchmark-style
  headline jumps.
- Large gains generally require typed hot loops, memoryviews, or other
  structure-aware tuning.
- Some aggressive directives change behavior or remove safety checks.
- Compiled modules add per-platform and per-Python-version build concerns.
- Pure-Python mode with `.pxd` augmentation creates synchronization work
  between the `.py` and `.pxd` surfaces.

### Cython conclusion for this repository

Cython is only a plausible future option for a small number of isolated
CPU-bound helper functions such as selected parsing or array-processing paths.
It is not a credible architecture for fully automatic, zero-risk conversion of
the full Django/OMERO codebase.

## Other automatic or semi-automatic acceleration options

### CPython upgrade or experimental JIT

- Most automatic option
- Lowest operational disruption if the target stack supports the runtime
- Current official CPython guidance still treats the JIT as experimental
- Expected gains are workload-dependent and not reliably dramatic

### PyPy

- Very automatic for pure-Python workloads
- Can improve some algorithmic code materially
- Not a guaranteed drop-in replacement for CPython stacks with extension-heavy
  dependencies
- Risk is elevated here because this repository depends on OMERO and native
  runtime integrations

### Nuitka

- More automatic than Cython in the sense that it compiles whole programs with
  strong CPython compatibility goals
- Still adds compiled build artifacts and packaging complexity
- Does not guarantee dramatic gains for I/O-bound application code

### mypyc

- Can accelerate strongly typed Python
- Not fully automatic because it depends on disciplined type information and
  has documented behavioral differences

### Numba and Pythran

- Excellent for specific numeric kernels
- Not general whole-application solutions for Django/OMERO code
- Require code to fit a supported subset or array-oriented model

### Codon or another language-like Python compiler

- Potentially very fast
- Not drop-in compatible with CPython
- Better framed as a partial rewrite or subsystem port than as transparent
  whole-repo acceleration

## Articles and community feedback reviewed

The reviewed articles and threads consistently support the same pattern:

- dramatic wins come from loop-heavy CPU code
- selective targeting works better than blanket conversion
- I/O-heavy code sees small or negligible benefit
- blind Cythonization creates debugging and maintenance pain

This includes benchmark-style tutorials and community discussions around:

- Cython-only examples with typed loops
- Django and automation-script experiences
- Cython adoption feedback from forum and Q&A threads

## Strict architecture rankings

These rankings are repository-specific. They are not generic Python advice.

### Ranking 1: Most automatic to least automatic

| Rank | Option | Why it ranks here |
| --- | --- | --- |
| 1 | Newer CPython runtime experiment | Smallest code change surface; mostly environment and compatibility work |
| 2 | PyPy feasibility spike | Runtime swap is simpler than source conversion, but dependency risk is real |
| 3 | Nuitka package build spike | Broad compilation is relatively automatic, but packaging complexity rises immediately |
| 4 | Bulk Cython compilation without typing | Can be automated, but expected gains are limited and compatibility still needs validation |
| 5 | Selective typed Cython | Stronger upside, but no longer "automatic" once types and directives are introduced |
| 6 | mypyc | Requires stronger typing discipline and behavior review |
| 7 | Numba or Pythran | Effective only for narrow numeric subsets |
| 8 | Codon or another Python-like language port | Not a transparent conversion path for this stack |

### Ranking 2: Lowest behavior risk to highest behavior risk

| Rank | Option | Why it ranks here |
| --- | --- | --- |
| 1 | Profiling-led Python refactors in CPython | Keeps semantics under direct repository control |
| 2 | Newer stable CPython runtime without JIT-only assumptions | Lowest platform drift among runtime-level changes |
| 3 | Nuitka feasibility spike | Strong compatibility goal, but compiled-distribution complexity remains |
| 4 | Selective Cython on isolated helper functions | Risk can be bounded to small modules with strong tests |
| 5 | PyPy | Dependency and extension behavior can diverge from CPython |
| 6 | mypyc | Documented semantic differences and typing constraints |
| 7 | Numba or Pythran | Supported-subset restrictions make behavior drift more likely if overextended |
| 8 | Codon or subsystem port to another language | Highest divergence from the current runtime model |

### Ranking 3: Most likely to produce measurable improvement in this repository

| Rank | Option | Why it ranks here |
| --- | --- | --- |
| 1 | Profiling plus Python-level architecture cleanup | Most large modules are I/O and integration heavy, so batching, caching, and path reduction are more promising than compilation alone |
| 2 | Isolate and optimize the few CPU-heavy helpers | Gives a clean target for later compiled acceleration if profiling justifies it |
| 3 | Selective Cython for proven hotspots | Plausible for narrow parsing or array-processing paths only |
| 4 | Newer CPython runtime experiment | Worth testing, but gains are likely incremental |
| 5 | PyPy feasibility spike | Could help pure-Python hotspots, but extension risk is high for this stack |
| 6 | Nuitka build experiment | Useful if packaging goals align, but not the most likely source of large runtime wins here |
| 7 | mypyc | Better fit for typed application cores than this mixed integration surface |
| 8 | Numba, Pythran, or Codon | Narrow or incompatible fit for the repository's dominant workloads |

### Ranking 4: Recommended future implementation order if this work resumes

| Rank | Next step | Reason |
| --- | --- | --- |
| 1 | Build a profiling baseline for representative OMERO.web and import workflows | Establishes where time is actually spent |
| 2 | Trim Python-level bottlenecks first | Lowest risk and most likely immediate payoff |
| 3 | Carve out CPU-bound helpers into small, testable modules | Creates clean boundaries for any future compiler work |
| 4 | Benchmark selective Cython only on proven hotspots | Highest credibility compiled path for this repo |
| 5 | Run a bounded newer-CPython experiment | Cheap data point if the stack supports it |
| 6 | Run a bounded PyPy or Nuitka feasibility spike only after hotspot isolation | Avoids measuring toolchains against the wrong workload |

## Practical guardrails for any future acceleration work

- Do not compile tests by default.
- Do not compile Django views, request handlers, or OMERO integration glue
  blindly.
- Treat filesystem, network, subprocess, and OMERO round-trip latency as
  separate from pure Python execution time.
- Require profiling evidence before introducing a compiler toolchain.
- Keep a pure-Python fallback until a compiled path has passed the full test
  matrix and deployment validation.
- Evaluate performance changes against representative workflows, not microbench
  loops.

## Sources consulted

### Primary sources

- [Cython releases](https://github.com/cython/cython/releases)
- [Cython pure Python mode](https://cython.readthedocs.io/en/3.1.x/src/tutorial/pure.html)
- [Cython FAQ](https://cython.readthedocs.io/en/3.0.x/src/userguide/faq.html)
- [Cython source files and compilation](https://cython.readthedocs.io/en/latest/src/userguide/source_files_and_compilation.html)
- [Cython cdef classes tutorial](https://cython.readthedocs.io/en/3.1.x/src/tutorial/cdef_classes.html)
- [Setuptools extension modules guide](https://setuptools.pypa.io/en/stable/userguide/ext_modules.html)
- [What's New In Python 3.14](https://docs.python.org/3.14/whatsnew/3.14.html)
- [PyPy home page](https://pypy.org/)
- [PyPy FAQ](https://doc.pypy.org/en/latest/faq.html)
- [Nuitka overview](https://nuitka.net/pages/overview.html)
- [Nuitka user manual](https://nuitka.net/user-documentation/user-manual.html)
- [mypyc getting started](https://mypyc.readthedocs.io/en/latest/getting_started.html)
- [mypyc differences from Python](https://mypyc.readthedocs.io/en/stable/differences_from_python.html)
- [Numba supported Python features](https://numba.readthedocs.io/en/stable/reference/pysupported.html)
- [Pythran documentation](https://pythran.readthedocs.io/en/latest/)
- [Codon repository](https://github.com/exaloop/codon)

### Secondary sources reviewed for examples and user feedback

- [MachineLearningPlus Cython article](https://machinelearningplus.com/python/how-to-convert-python-code-to-cython-and-speed-up-100x/)
- [DigitalOcean Cython tutorial](https://www.digitalocean.com/community/tutorials/boosting-python-scripts-cython)
- [Stackademic Cython write-up](https://blog.stackademic.com/i-tried-speeding-up-python-with-cython-for-a-week-heres-what-really-happened-949e5635aa7f)
- [Reddit discussion on easy Python conversion](https://www.reddit.com/r/learnpython/comments/12deyvw/are_there_any_libraries_that_can_easily_convert/)
- [Stack Overflow discussion on Cython with Django](https://stackoverflow.com/questions/3539120/using-cython-with-django-does-it-make-sense)
- [Cython-users discussion thread](https://groups.google.com/g/cython-users/c/WYZSUjKFaQk)
