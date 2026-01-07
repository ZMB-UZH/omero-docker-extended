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
    # NUMBERS & MATHEMATICS
    # -------------------------------------------------------------------------
    r'\d',                                      # Negative numbers: -5, -0.25, -100
    
    # -------------------------------------------------------------------------
    # CHEMICAL NOMENCLATURE (IUPAC)
    # -------------------------------------------------------------------------
    r'[A-Z]{1,4}(?:\d+[A-Z]*)?(?=[^a-z]|$)',   # Chemical compounds: 5-HT, 5-HT2A, 3-MA, 20-HETE
    r'd\d+',                                    # Deuterated solvents: DMSO-d6, CDCl3-d1, MeOD-d4
    r'\d+(?=[^a-zA-Z]|$)',                     # Chemical codes: ATP-2, DMSO-5, NADPH-1
    
    # -------------------------------------------------------------------------
    # SCIENTIFIC MEASUREMENTS
    # -------------------------------------------------------------------------
    r'\d+\.?\d*(?=[^a-zA-Z]|$)',               # pH values: pH-7.4, pH-8.0, pH-6.5
    r'[CcFfKk](?=[^a-zA-Z]|$)',                # Temperature: -20C, 37C, 273K, -80F, 98.6F
    
    # -------------------------------------------------------------------------
    # BIOLOGY - GREEK LETTER PREFIXES
    # -------------------------------------------------------------------------
    r'[A-Za-z]{2,}',                            # After Greek: α-SMA, β-actin, γ-tubulin, δ-opioid
    
    # -------------------------------------------------------------------------
    # BIOLOGY - SINGLE LETTER SCIENTIFIC NOTATION
    # -------------------------------------------------------------------------
    r'[a-z]+',                                  # T-cell, B-cell, N-terminus, C-terminus, H-bond
    r'[A-Z]+(?=[^a-z]|$)',                     # X-RAY, UV-A, UV-B, UV-C, T-TEST, P-VALUE
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - FLUOROPHORES & DYES
    # -------------------------------------------------------------------------
    r'[A-Z][A-Z]+',                             # Cy5-NHS, FITC-BSA, TRITC-dextran, DAPI-stained
    r'[a-z]+(?:ed|ing|ate|able|ated)',         # conjugated, tagged, stained, labeled, activated
    r'[A-Za-z]+\d+',                            # Alexa488-NHS, Alexa647-conjugated, Atto565-maleimide
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - WAVELENGTH & DIMENSIONS
    # -------------------------------------------------------------------------
    r'[a-z]+',                                  # 488nm-laser, 561nm-channel, 10um-section, 100nm-beads
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - MAGNIFICATION & OPTICS
    # -------------------------------------------------------------------------
    r'[a-z]+',                                  # 20x-objective, 40X-lens, 100x-oil, 63x-water
    
    # -------------------------------------------------------------------------
    # MICROSCOPY - DIMENSIONAL NOTATION (REMBI/OME)
    # -------------------------------------------------------------------------
    r'[a-z]+',                                  # Z-stack, T-series, C-plane, Z-projection
    r'(?:image|frame|plane|slice|section)',     # Z01-image, T05-frame, C03-plane, Z10-slice
    
    # -------------------------------------------------------------------------
    # MOLECULAR BIOLOGY - PROTEIN TAGS & CONSTRUCTS
    # -------------------------------------------------------------------------
    r'(?:tagged|fusion|expressing|driven|positive|negative)', # GFP-tagged, mCherry-fusion
    r'[Ll]ox',                                  # Cre-lox, flox-FRT, loxP-flanked
    r'(?:GFP|RFP|YFP|CFP|BFP)',                # anti-GFP, pro-RFP, EGFP-N1
    
    # -------------------------------------------------------------------------
    # CHEMISTRY - PREFIXES & MODIFICATIONS
    # -------------------------------------------------------------------------
    r'(?:terminus|terminal|bond|linked|directed)',  # N-terminus, C-terminal, H-bond, O-linked
    r'glycosylation',                           # O-glycosylation, N-glycosylation
    r'(?:acetyl|methyl|ethyl|phospho)',        # N-acetyl, O-methyl, S-ethyl, O-phospho
    
    # -------------------------------------------------------------------------
    # DATE & TIME FORMATS (ISO 8601)
    # -------------------------------------------------------------------------
    r'\d{2}(?:-\d{2})?',                       # 2024-01-15, 2024-01, 15-01-2024
    r'\d+[hms](?:r)?',                         # 24h-timepoint, 5min-interval, 30s-exposure, 2hr-treatment
    
    # -------------------------------------------------------------------------
    # STATISTICS & MATHEMATICS
    # -------------------------------------------------------------------------
    r'(?:test|tailed|way|sided|value)',        # t-test, two-tailed, one-way, double-sided, p-value
    
    # -------------------------------------------------------------------------
    # BIOLOGY - SAMPLE & STRAIN NOTATION
    # -------------------------------------------------------------------------
    r'(?:WT|KO|HET|background|type)',          # wild-type, knock-out, C57BL/6-background, mock-treated
    
    # -------------------------------------------------------------------------
    # ANTIBODIES & IMMUNOLOGY
    # -------------------------------------------------------------------------
    r'[A-Za-z]+(?:\d+)?',                      # anti-CD4, anti-mouse, anti-rabbit, anti-IgG
    
    # -------------------------------------------------------------------------
    # EXPERIMENTAL CONDITIONS
    # -------------------------------------------------------------------------
    r'(?:treated|starved|stimulated|induced|depleted|supplemented)',  # serum-starved, drug-treated
    r'(?:free|containing|rich|poor)',          # serum-free, glucose-containing, nutrient-rich
    
    # -------------------------------------------------------------------------
    # CELLULAR COMPARTMENTS & ORGANELLES
    # -------------------------------------------------------------------------
    r'(?:associated|bound|localized|resident)', # membrane-associated, ER-resident, nucleus-localized
    
    # -------------------------------------------------------------------------
    # IMAGING MODALITIES & TECHNIQUES
    # -------------------------------------------------------------------------
    r'(?:FRET|FLIM|FRAP|TIRF|SIM|STED|PALM|STORM)', # FRET-imaging, TIRF-microscopy
    r'(?:confocal|widefield|lightsheet)',       # confocal-microscopy, light-sheet imaging
]
