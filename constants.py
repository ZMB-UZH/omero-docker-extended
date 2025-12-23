import os

PLUGIN_DISPLAY_NAME = "OMP plugin" # NOT applicable here: need to change the docker-compose file

# Storage directory for job JSON files
# Description: Create the directory. No error if it already exists. Root access to the host machine assumed.
JOBS_DIR = "/tmp/omp_plugin_filename_metadata_jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

# Chunk size for processing progress
# Smaller chunks yield more responsive progress updates.
_DEFAULT_CHUNK_SIZE = 5
try:
    CHUNK_SIZE = int(os.environ.get("OMP_CHUNK_SIZE", _DEFAULT_CHUNK_SIZE))
except (TypeError, ValueError):
    CHUNK_SIZE = _DEFAULT_CHUNK_SIZE
CHUNK_SIZE = max(1, CHUNK_SIZE)

# Default variable names (partially REMBI-aligned)
DEFAULT_VARIABLE_NAMES = [
    "Project number",
    "Sample type",
    "Substrate",
    "Position",
    "Image acquisition",
    "Specific experimental conditions",
]

# Maximum number of variable sets stored per user.
MAX_VARIABLE_SET_ENTRIES = 10

# Namespaces used for MapAnnotations
MAP_NS = "openmicroscopy.org/omero/client/mapAnnotation" # default client namespace that allows editing in Omero Web

# -----------------------------------------------------------------------------
# Plugin marker (hash) for safe "delete only what this plugin created"
# -----------------------------------------------------------------------------
# Key appended to MapAnnotation key-value pair sets
HASH_KEY = "omp_hash"

# Prefix stored as the value of HASH_KEY
HASH_PREFIX = "omphash_v1:"

# Stable plugin identifier used in the hash payload
PLUGIN_ID = "omeroweb_omp_plugin"

# Optional secret for hashing. If unset/empty, hashing falls back to plain SHA256, which anyone could theoretically forge.
# Recommended: set this as an environment variable for Omero web container.
HASH_SECRET_ENV = "FMP_HASH_SECRET"
