import os

from omero_plugin_common.env_utils import ENV_FILE_OMEROWEB, get_env
import time
import logging

logger = logging.getLogger(__name__)

# OMERO.web virtualenv (used for CLI and other tooling).
# Override via environment when the venv name changes.
OMERO_WEB_ROOT = get_env("OMERO_WEB_ROOT", env_file=ENV_FILE_OMEROWEB)
OMERO_WEB_VENV = get_env("OMERO_WEB_VENV", env_file=ENV_FILE_OMEROWEB)
OMERO_CLI = os.path.join(OMERO_WEB_ROOT, OMERO_WEB_VENV, "bin", "omero")

# Storage directory for job JSON files
# Create the directory. No error if it already exists. Root access to the host machine assumed.
JOBS_DIR = "/tmp/omp_plugin_filename_metadata_jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

# Chunk size for data processing
# Smaller chunks yield more responsive progress updates.
CHUNK_SIZE = 5

# Default variable names (REMBI-aligned)
DEFAULT_VARIABLE_NAMES = [
    "Project number",
    "Sample type",
    "Substrate",
    "Position",
    "Image acquisition",
    "Specific experimental conditions",
]

# Maximum number of variables that can be parsed from filenames
MAX_PARSED_VARIABLES = 10

# Maximum number of variable sets that can stored per user in the plugin database.
# Limits both the number of variable name input fields and the number of parsed variables.
MAX_VARIABLE_SET_ENTRIES = 10

# Whitelist of common, safe separators for filename parsing
# Prevents weird Unicode characters from being chosen as separators
COMMON_SEPARATORS = ['_', '-', '.', ' ', '__']

# Namespaces used for MapAnnotations
MAP_NS = "openmicroscopy.org/omero/client/mapAnnotation" # default client namespace that allows editing in OMERO.web

# Plugin prefix marker (hash) for safe delete only what this plugin created

# Key appended to MapAnnotation key-value pair sets
HASH_KEY = "omp_hash"

# Prefix stored as the value of HASH_KEY
HASH_PREFIX = "omphash_v1:"

# Stable plugin identifier used in the hash payload
PLUGIN_ID = "omeroweb_omp_plugin"

# Optional secret for hashing. If unset/empty, hashing falls back to plain SHA256, which anyone could theoretically forge.
# Recommended: set this as an environment variable for OMERO.web container.
HASH_SECRET_ENV = "FMP_HASH_SECRET"

# Major action per-user rate limiter parameters
MAJOR_ACTION_LIMIT = 6
MAJOR_ACTION_WINDOW_SECONDS = 60
MAJOR_ACTION_BLOCK_SECONDS = 60

# Job cleanup parameters (prevent RAM hogging)
JOB_MAX_AGE_SECONDS = 7200  # Delete jobs older than 2 hours - increase if problem with ultralong jobs appear
JOB_CLEANUP_INTERVAL = 300  # Run cleanup every 5 minutes

# Hyphen protection patterns for scientific nomenclature, used in "Local Regex" creation
PROTECTED_HYPHEN_PATTERNS = [
    r'[A-Za-z]+\d+',                                    # Chemical: DMSO-d6, 5-HT2A
    r'(?<=\d)[A-Z]{1,3}(?:\d+)?(?=\W|$)',              # After digit: 5-HT, 20-HETE
    r'(?<=[ZTC])(?:stack|series|plane|projection)',     # Z-stack, T-series
    r'(?<=x)(?:objective|oil|water)',                   # 20x-objective
    r'(?<=X)(?:objective|lens)',                        # 20X-objective
    r'(?<=m)(?:laser|channel|filter)',                  # 488nm-laser
    r'(?<=[TB])cell',                                    # T-cell, B-cell
    r'(?<=[NOHSC])(?:terminus|terminal|bond|linked)',   # N-terminus, H-bond
    r'(?<=P)(?:GFP|RFP|YFP)',                           # anti-GFP
    r'(?<=t)test',                                       # t-test
    r'(?<=p)value',                                      # p-value
]
