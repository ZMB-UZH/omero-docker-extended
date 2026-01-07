"""
Filename parsing utilities for OMERO metadata plugin.

Provides shared functions for extracting base names and building regex patterns
with intelligent hyphen protection for scientific nomenclature.
"""

import re
from ..constants import PROTECTED_HYPHEN_PATTERNS


def extract_base_name(filename):
    """
    Extract the meaningful base name from a filename.
    
    Handles common microscopy filename formats:
    - Bracketed names: "prefix [basename].ext" -> "basename"
    - Whitespace-delimited: "prefix basename.ext" -> "basename"
    - Simple names: "basename.ext" -> "basename"
    
    Args:
        filename (str): The filename to process
        
    Returns:
        str: The extracted base name without extension
        
    Examples:
        >>> extract_base_name("IMG [sample-001].tif")
        'sample-001'
        >>> extract_base_name("20240115 experiment-A.tif")
        'experiment-A'
        >>> extract_base_name("image_001.tif")
        'image_001'
    """
    # Check for bracketed format: "prefix [basename].ext"
    match = re.search(r"\[(.+?)\]", filename)
    if match:
        return match.group(1)
    
    # Normalize tabs to spaces
    sanitized = filename.replace("\t", " ")
    
    # Check for whitespace-delimited format: "prefix basename.ext"
    match = re.search(r".*\s+(.+?)\s*$", sanitized)
    if match:
        return match.group(1).rsplit(".", 1)[0]
    
    # Fall back to simple format: "basename.ext"
    return filename.rsplit(".", 1)[0]


def build_hyphen_protection_pattern():
    """
    Build comprehensive negative lookahead pattern for hyphen protection.
    
    Combines all protected patterns from PROTECTED_HYPHEN_PATTERNS into a single
    regex that identifies hyphens that should NOT be treated as separators.
    
    Returns:
        str: Regex pattern for negative lookahead after hyphen
        
    Examples:
        Pattern protects: -5, 5-HT, pH-7.4, T-cell, Z-stack, 2024-01-15
        Pattern allows split: sample-001, test-case, image-data
    """
    # Build comprehensive negative lookahead from all protected patterns
    protected_conditions = [f'(?:{pattern})' for pattern in PROTECTED_HYPHEN_PATTERNS]
    return '|'.join(protected_conditions)


def regex_for_separators(separators, label_tokens=None):
    """
    Generate regex pattern for filename field separators with intelligent hyphen protection.
    
    This function creates a regex pattern that splits filenames on separator characters
    while protecting hyphens that are part of scientific terms (chemical compounds,
    biological nomenclature, measurements, etc.).
    
    Args:
        separators (str or list): Characters to use as separators (e.g., '_', '-', '.')
        label_tokens (list, optional): Label tokens that may appear between separators.
                                       Used for more sophisticated pattern matching.
                                       If None, returns simple separator pattern.
    
    Returns:
        str: Regex pattern suitable for re.split()
        
    Examples:
        >>> regex_for_separators('_-')
        '(?:_|-(?!...protected patterns...))+'
        
        >>> regex_for_separators('_', ['T', 'Z'])
        '(?:_(?:T|Z)_|_|^(?:T|Z)_|_(?:T|Z)$)'
    
    Protected hyphen examples:
        - Chemical: 5-HT, DMSO-d6, pH-7.4
        - Biology: T-cell, α-SMA, GFP-tagged
        - Microscopy: Z-stack, 488nm-laser, 20x-objective
        - Dates: 2024-01-15
        - Measurements: -20C, 10um-section
    """
    tokens = []
    has_whitespace = False
    
    for char in separators:
        if char.isspace():
            has_whitespace = True
        elif char == "-":
            # Apply comprehensive hyphen protection
            protected_lookahead = build_hyphen_protection_pattern()
            tokens.append(f'-(?!{protected_lookahead})')
        else:
            # Escape other special regex characters
            tokens.append(re.escape(char))
    
    # Add whitespace pattern if any whitespace separator was found
    if has_whitespace:
        tokens.append(r"\s")
    
    # If no valid separators, fall back to digit/non-digit boundary
    if not tokens:
        return r"(?<=\D)(?=\d)|(?<=\d)(?=\D)"
    
    # Build basic separator pattern
    sep_pattern = "(?:" + "|".join(tokens) + ")+"
    
    # If no label tokens, return simple pattern
    if not label_tokens:
        return sep_pattern
    
    # Build pattern that handles labels between separators
    # This allows for patterns like: "sep LABEL sep" or "^LABEL sep" or "sep LABEL$"
    label_pattern = "(?:" + "|".join(re.escape(token) for token in label_tokens) + ")"
    
    return (
        "(?:"
        + sep_pattern               # Separator + label + separator
        + label_pattern
        + sep_pattern
        + "|"
        + sep_pattern               # Just separator
        + "|^"
        + label_pattern             # Label at start + separator
        + sep_pattern
        + "|"
        + sep_pattern               # Separator + label at end
        + label_pattern
        + "$)"
    )
