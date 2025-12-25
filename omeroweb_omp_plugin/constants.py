import os

# Storage directory for job JSON files
# Create the directory. No error if it already exists. Root access to the host machine assumed.
JOBS_DIR = "/tmp/omp_plugin_filename_metadata_jobs"
os.makedirs(JOBS_DIR, exist_ok=True)

# Chunk size for data processing
# Smaller chunks yield more responsive progress updates.
CHUNK_SIZE = 5

# Maximum number of variable sets that can stored per user in the plugin database.
# Limits both the number of variable name input fields and the number of parsed variables.
MAX_VARIABLE_SET_ENTRIES = 10

# Maximum number of variables that can be parsed from filenames
MAX_PARSED_VARIABLES = 15

# Default variable names (partially REMBI-aligned)
DEFAULT_VARIABLE_NAMES = [
    "Project number",
    "Sample type",
    "Substrate",
    "Position",
    "Image acquisition",
    "Specific experimental conditions",
]

# Namespaces used for MapAnnotations
MAP_NS = "openmicroscopy.org/omero/client/mapAnnotation" # default client namespace that allows editing in Omero Web

# Plugin prefix marker (hash) for safe delete only what this plugin created

# Key appended to MapAnnotation key-value pair sets
HASH_KEY = "omp_hash"

# Prefix stored as the value of HASH_KEY
HASH_PREFIX = "omphash_v1:"

# Stable plugin identifier used in the hash payload
PLUGIN_ID = "omeroweb_omp_plugin"

# Optional secret for hashing. If unset/empty, hashing falls back to plain SHA256, which anyone could theoretically forge.
# Recommended: set this as an environment variable for Omero web container.
HASH_SECRET_ENV = "FMP_HASH_SECRET"

# Major action per-user rate limiter parameters
MAJOR_ACTION_LIMIT = 6
MAJOR_ACTION_WINDOW_SECONDS = 60
MAJOR_ACTION_BLOCK_SECONDS = 60

