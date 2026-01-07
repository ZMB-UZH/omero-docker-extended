import os
import time
import logging

logger = logging.getLogger(__name__)

# Omero web virtualenv (used for CLI and other tooling).
# Override via environment when the venv name changes.
OMERO_WEB_ROOT = os.environ.get("OMERO_WEB_ROOT", "/opt/omero/web")
OMERO_WEB_VENV = os.environ.get("OMERO_WEB_VENV", "venv-3.12")
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

# Job cleanup parameters (prevent RAM hogging)
JOB_MAX_AGE_SECONDS = 7200  # Delete jobs older than 2 hours - increase if problem with ultralong jobs appear
JOB_CLEANUP_INTERVAL = 300  # Run cleanup every 5 minutes

# ==============================================================================
# HYPHEN PROTECTION PATTERNS FOR SCIENTIFIC NOMENCLATURE
# ==============================================================================
# Comprehensive patterns based on:
# - REMBI (Recommended Metadata for Biological Images) standards
# - OME (Open Microscopy Environment) conventions
# - IUPAC chemical nomenclature
# - Common microscopy/biology/chemistry filename patterns
# - ISO 8601 date/time formats
# 
# These patterns protect hyphens that are part of scientific terms rather than
# field separators in filenames.
# ==============================================================================

PROTECTED_HYPHEN_PATTERNS = [
    # =========================================================================
    # CORE PATTERN - Chemical compound protection
    # =========================================================================
    # Protects: DMSO-d6, 5-HT2A, ATP-2 (letters immediately followed by digits)
    # Allows split: sample-001, ec-01, test-case (normal separators)
    r'[A-Za-z]+\d',
    
    # =========================================================================
    # ADDITIONAL SPECIFIC SCIENTIFIC PATTERNS
    # =========================================================================
    # Only fixed-width lookbehinds are used to avoid regex errors
    
    # Chemical compounds with digit prefix (5-HT, 20-HETE)
    r'(?<=\d)[A-Z]{1,3}(?:\d+)?(?=\W|$)',
    
    # Microscopy dimensional notation
    r'(?<=[ZTC])(?:stack|series|plane|projection)',  # Z-stack, T-series, C-plane
    
    # Magnification and optics
    r'(?<=x)(?:objective|oil|water)',                # 20x-objective, 100x-oil
    r'(?<=X)(?:objective|lens)',                     # 20X-objective, 40X-lens
    
    # Wavelength notation
    r'(?<=m)(?:laser|channel|filter)',               # 488nm-laser, 561nm-channel
    
    # Biology single-letter prefixes
    r'(?<=[TB])cell',                                 # T-cell, B-cell
    r'(?<=[NOHSC])(?:terminus|terminal|bond|linked)', # N-terminus, H-bond, O-linked
    
    # Protein tags
    r'(?<=P)(?:GFP|RFP|YFP)',                        # anti-GFP, anti-RFP
    
    # Statistics
    r'(?<=t)test',                                    # t-test
    r'(?<=p)value',                                   # p-value
]
