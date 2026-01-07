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
    # NEGATIVE NUMBERS - Simple lookahead, no lookbehind needed
    # -------------------------------------------------------------------------
    r'\d',                                      # -5, -0.25, -100
    
    # -------------------------------------------------------------------------
    # CHEMICAL NOMENCLATURE - Use word boundaries instead of variable lookbehind
    # -------------------------------------------------------------------------
    r'(?<=\d)[A-Z]{1,4}(?:\d+[A-Z]*)?(?=\W|$)', # After digit: 5-HT, 3-MA, 20-HETE
    r'd\d+(?=\W|$)',                             # Deuterated: DMSO-d6 (check after, not before)
    r'(?<=\d)\d+(?=\W|$)',                      # After digit: ATP-2 style
    
    # -------------------------------------------------------------------------
    # pH VALUES
    # -------------------------------------------------------------------------
    r'(?<=H)\d+\.?\d*',                         # After pH: pH-7.4 (fixed-width H)
    
    # -------------------------------------------------------------------------
    # TEMPERATURE - Check what comes after
    # -------------------------------------------------------------------------
    r'\d+[CcFfKk](?=\W|$)',                     # Handles -20C, 37C
    
    # -------------------------------------------------------------------------
    # SINGLE LETTER PREFIXES - Fixed single character
    # -------------------------------------------------------------------------
    r'(?<=[TBXNHCOSZ])cell',                    # T-cell, B-cell (single letter)
    r'(?<=[TBXNHCOSZ])ray',                     # X-ray
    r'(?<=[TBXNHCOSZ])test',                    # T-test
    r'(?<=[NOHSC])terminus',                    # N-terminus, C-terminus
    r'(?<=[NOHSC])terminal',                    # N-terminal, C-terminal
    r'(?<=[NOHSC])bond',                        # H-bond, C-bond
    r'(?<=[NOHSC])linked',                      # O-linked, N-linked
    r'(?<=[NOHSC])glycosylation',               # O-glycosylation
    r'(?<=[NOHSC])acetyl',                      # N-acetyl, O-acetyl
    r'(?<=[ZTC])stack',                         # Z-stack
    r'(?<=[ZTC])series',                        # T-series
    r'(?<=[ZTC])plane',                         # C-plane
    r'(?<=[ZTC])projection',                    # Z-projection
    r'(?<=[UV])(?:[A-C](?=\W|$))',             # UV-A, UV-B, UV-C
    
    # -------------------------------------------------------------------------
    # COMMON SCIENTIFIC SUFFIXES - Check after hyphen
    # -------------------------------------------------------------------------
    r'conjugated',                              # FITC-conjugated, Alexa488-conjugated
    r'tagged',                                  # GFP-tagged, His-tagged
    r'labeled',                                 # DAPI-labeled
    r'stained',                                 # DAPI-stained
    r'expressing',                              # EGFP-expressing
    r'fusion',                                  # mCherry-fusion
    r'positive',                                # GFP-positive
    r'negative',                                # control-negative
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - SPECIFIC TERMS
    # -------------------------------------------------------------------------
    r'(?<=m)laser',                             # 488nm-laser (m is fixed)
    r'(?<=m)channel',                           # 561nm-channel
    r'(?<=m)filter',                            # 640nm-filter
    r'(?<=m)section',                           # 10um-section
    r'(?<=m)slice',                             # 5um-slice
    r'(?<=x)objective',                         # 20x-objective (x is fixed)
    r'(?<=x)lens',                              # 40x-lens
    r'(?<=x)oil',                               # 100x-oil
    r'(?<=X)objective',                         # 20X-objective
    r'(?<=X)lens',                              # 40X-lens
    
    # -------------------------------------------------------------------------
    # PROTEIN/ANTIBODY NAMES - Specific matches
    # -------------------------------------------------------------------------
    r'(?<=P)GFP',                               # anti-GFP (check for anti later)
    r'(?<=P)RFP',                               # anti-RFP
    r'(?<=P)YFP',                               # anti-YFP
    r'NHS(?=\W|$)',                             # Cy5-NHS, anything-NHS
    
    # -------------------------------------------------------------------------
    # GENETICS - Specific terms
    # -------------------------------------------------------------------------
    r'(?<=e)lox',                               # Cre-lox (e is fixed)
    r'(?<=x)Cre',                               # lox-Cre (x is fixed)
    r'(?<=x)FRT',                               # flox-FRT (x is fixed)
    r'(?<=d)type',                              # wild-type (d is fixed)
    r'(?<=k)out',                               # knock-out (k is fixed)
    r'(?<=k)in',                                # knock-in
    r'(?<=k)down',                              # knock-down
    
    # -------------------------------------------------------------------------
    # ISO DATES - Digit patterns
    # -------------------------------------------------------------------------
    r'(?<=\d)\d{2}-\d{2}(?=\W|$)',             # After 4 digits: 2024-01-15
    r'\d{2}-\d{2}-\d{4}',                       # 15-01-2024 format
    r'\d{4}-\d{2}-\d{2}',                       # 2024-01-15 format (full)
    
    # -------------------------------------------------------------------------
    # TIME NOTATION
    # -------------------------------------------------------------------------
    r'(?<=h)timepoint',                         # 24h-timepoint (h is fixed)
    r'(?<=h)treatment',                         # 2h-treatment
    r'(?<=h)incubation',                        # 4h-incubation
    r'(?<=n)interval',                          # 5min-interval (n is fixed)
    r'(?<=n)treatment',                         # 10min-treatment
    r'(?<=n)exposure',                          # 30min-exposure
    r'(?<=s)exposure',                          # 30s-exposure (s is fixed)
    r'(?<=s)pulse',                             # 1s-pulse
    
    # -------------------------------------------------------------------------
    # STATISTICS
    # -------------------------------------------------------------------------
    r'(?<=t)test',                              # t-test (t is fixed)
    r'(?<=p)value',                             # p-value (p is fixed)
    r'(?<=o)tailed',                            # two-tailed (o is fixed)
    r'(?<=o)way',                               # two-way, one-way
    
    # -------------------------------------------------------------------------
    # TREATMENT CONDITIONS
    # -------------------------------------------------------------------------
    r'(?<=m)free',                              # serum-free (m is fixed)
    r'(?<=m)starved',                           # serum-starved
    r'(?<=m)depleted',                          # serum-depleted
    r'(?<=e)free',                              # glucose-free (e is fixed)
    r'(?<=g)treated',                           # drug-treated (g is fixed)
    r'(?<=g)resistant',                         # drug-resistant
    
    # -------------------------------------------------------------------------
    # IMAGING TECHNIQUES
    # -------------------------------------------------------------------------
    r'(?<=T)imaging',                           # FRET-imaging (T is fixed)
    r'(?<=M)imaging',                           # FLIM-imaging (M is fixed)
    r'(?<=P)imaging',                           # FRAP-imaging (P is fixed)
    r'(?<=F)imaging',                           # TIRF-imaging (F is fixed)
    r'(?<=T)microscopy',                        # FRET-microscopy
    r'(?<=l)microscopy',                        # confocal-microscopy (l is fixed)
]

