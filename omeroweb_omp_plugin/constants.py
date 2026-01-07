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
    # -------------------------------------------------------------------------
    # NEGATIVE NUMBERS
    # -------------------------------------------------------------------------
    r'\d',                                      # After hyphen: -5, -0.25, -100
    
    # -------------------------------------------------------------------------
    # CHEMICAL NOMENCLATURE (IUPAC) - Number prefix required
    # -------------------------------------------------------------------------
    r'(?<=\d-)[A-Z]{1,4}(?:\d+[A-Z]*)?(?=[^a-z]|$)',   # 5-HT, 5-HT2A, 3-MA, 20-HETE (MUST have digit before)
    r'(?<=[A-Z]{2}-)d\d+',                              # DMSO-d6, CDCl3-d1 (capitals before hyphen)
    r'(?<=[A-Z]{2}-)\d+',                               # ATP-2, NADPH-1 (capitals before hyphen)
    
    # -------------------------------------------------------------------------
    # SCIENTIFIC MEASUREMENTS - Context required
    # -------------------------------------------------------------------------
    r'(?<=pH-)\d+\.?\d*',                               # pH-7.4, pH-8.0
    r'(?<=-\d{1,3})[CcFfKk](?=[^a-zA-Z]|$)',           # -20C, 37C after number
    
    # -------------------------------------------------------------------------
    # BIOLOGY - GREEK LETTER PREFIXES (single Greek char)
    # -------------------------------------------------------------------------
    r'(?<=[α-ωΑ-Ω]-)[A-Za-z]{2,}',                     # α-SMA, β-actin (after Greek)
    
    # -------------------------------------------------------------------------
    # BIOLOGY - SINGLE LETTER SCIENTIFIC NOTATION
    # -------------------------------------------------------------------------
    r'(?<=\b[A-Z]-)(?:cell|ray|test|bond|terminus|terminal|linked|directed)', # T-cell, X-ray, H-bond, N-terminus
    r'(?<=\b[A-Z]-)(?:[A-Z]{2,}(?=[^a-z]|$))',         # UV-A, T-TEST (single letter then caps)
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - FLUOROPHORES (alphanumeric before hyphen)
    # -------------------------------------------------------------------------
    r'(?<=[A-Z][a-z]*\d+-)[A-Z]{2,}',                  # Cy5-NHS, Alexa488-NHS
    r'(?<=[A-Z]{2,}-)(?:conjugated|tagged|labeled|stained|activated)', # FITC-conjugated, DAPI-stained
    r'(?<=Alexa\d{3}-)(?:NHS|conjugated|labeled)',     # Alexa488-NHS, Alexa647-conjugated
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - WAVELENGTH & DIMENSIONS (number + unit before hyphen)
    # -------------------------------------------------------------------------
    r'(?<=\d+nm-)laser|channel|filter',                # 488nm-laser, 561nm-channel
    r'(?<=\d+[umn]m-)(?:section|slice|beads)',         # 10um-section, 100nm-beads
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - MAGNIFICATION
    # -------------------------------------------------------------------------
    r'(?<=\d+[xX]-)(?:objective|lens|oil|water)',      # 20x-objective, 100x-oil
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - DIMENSIONAL NOTATION (Z, T, C prefixes)
    # -------------------------------------------------------------------------
    r'(?<=\b[ZTC]-)(?:stack|series|plane|projection)', # Z-stack, T-series, C-plane
    r'(?<=\b[ZTC]\d{1,2}-)(?:image|frame|plane|slice)', # Z01-image, T05-frame
    
    # -------------------------------------------------------------------------
    # MOLECULAR BIOLOGY - PROTEIN TAGS (specific proteins before hyphen)
    # -------------------------------------------------------------------------
    r'(?<=GFP-|EGFP-|RFP-|YFP-|CFP-|mCherry-|tdTomato-)(?:tagged|fusion|expressing|positive|negative)',
    r'(?<=Cre-|lox-|flox-)(?:lox|Cre|FRT|flanked)',    # Cre-lox, lox-Cre, flox-FRT
    r'(?<=anti-)(?:GFP|RFP|YFP|CD\d+|mouse|rabbit|IgG)', # anti-GFP, anti-CD4
    
    # -------------------------------------------------------------------------
    # CHEMISTRY - SPECIFIC PREFIXES
    # -------------------------------------------------------------------------
    r'(?<=\b[NOHSC]-)(?:terminus|terminal|glycosylation|acetyl|methyl|linked)', # N-terminus, O-glycosylation
    
    # -------------------------------------------------------------------------
    # DATE FORMATS - ISO 8601 (strict digit patterns)
    # -------------------------------------------------------------------------
    r'(?<=\d{4}-)\d{2}-\d{2}',                         # 2024-01-15 (year-month-day)
    r'(?<=\d{2}-)\d{2}(?=-\d{2,4})',                   # 15-01-2024 (day-month part)
    
    # -------------------------------------------------------------------------
    # TIME NOTATION (number before unit)
    # -------------------------------------------------------------------------
    r'(?<=\d+h-)timepoint|treatment|incubation',        # 24h-timepoint, 2h-treatment
    r'(?<=\d+min-)interval|treatment|exposure',         # 5min-interval
    r'(?<=\d+s-)exposure|pulse|interval',               # 30s-exposure
    
    # -------------------------------------------------------------------------
    # STATISTICS (lowercase "t" or "p" before hyphen)
    # -------------------------------------------------------------------------
    r'(?<=\bt-)test',                                   # t-test
    r'(?<=\bp-)value',                                  # p-value
    r'(?<=two-)tailed|way|sided',                       # two-tailed, two-way
    
    # -------------------------------------------------------------------------
    # GENETICS - VERY SPECIFIC
    # -------------------------------------------------------------------------
    r'(?<=wild-)type',                                  # wild-type (specific)
    r'(?<=knock-)out|in|down',                          # knock-out, knock-in, knock-down
    r'(?<=C57BL/6-)background',                         # Mouse strain
    
    # -------------------------------------------------------------------------
    # TREATMENT CONDITIONS (specific prefixes)
    # -------------------------------------------------------------------------
    r'(?<=serum-)free|starved|depleted',                # serum-free, serum-starved
    r'(?<=glucose-)free|containing',                    # glucose-free
    r'(?<=drug-)treated|resistant',                     # drug-treated
    
    # -------------------------------------------------------------------------
    # SUBCELLULAR (specific prefixes)
    # -------------------------------------------------------------------------
    r'(?<=membrane-|ER-|nucleus-)(?:associated|bound|localized|resident)', 
    
    # -------------------------------------------------------------------------
    # IMAGING TECHNIQUES (specific acronyms)
    # -------------------------------------------------------------------------
    r'(?<=FRET-|FLIM-|FRAP-|TIRF-|SIM-|STED-|PALM-|STORM-)(?:imaging|microscopy|analysis)',
    r'(?<=confocal-|widefield-|lightsheet-)microscopy', 
]
