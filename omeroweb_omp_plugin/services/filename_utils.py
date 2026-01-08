"""
Filename parsing utilities with intelligent label-value pair detection.
"""

import re
from collections import Counter
from ..constants import PROTECTED_HYPHEN_PATTERNS


def extract_base_name(filename):
    """Extract the meaningful base name from a filename."""
    match = re.search(r"\[(.+?)\]", filename)
    if match:
        return match.group(1)
    sanitized = filename.replace("\t", " ")
    match = re.search(r".*\s+(.+?)\s*$", sanitized)
    if match:
        return match.group(1).rsplit(".", 1)[0]
    return filename.rsplit(".", 1)[0]


def detect_label_value_pairs(filenames):
    """
    Intelligently detect if filenames contain label-value pair patterns.
    
    Returns:
        tuple: (has_pairs, detected_labels)
            has_pairs: bool - True if >30% of parts are label-value pairs
            detected_labels: set - Set of detected label tokens
    """
    all_pairs = []
    total_parts = 0
    label_counts = Counter()
    
    for filename in filenames[:30]:  # Sample first 30 files
        base = extract_base_name(filename)
        parts = base.split('-')
        total_parts += len(parts)
        
        # Look for alpha-numeric pairs
        i = 0
        while i < len(parts) - 1:
            current = parts[i]
            next_part = parts[i + 1]
            
            # Check for label-value pattern:
            # - Current is 2-3 lowercase letters
            # - Next is digits
            if (current.isalpha() and 
                2 <= len(current) <= 3 and 
                current.islower() and 
                next_part.isdigit()):
                all_pairs.append((current, next_part))
                label_counts[current] += 1
                i += 2
            else:
                i += 1
    
    # Determine if this is a label-value pattern dataset
    pair_ratio = len(all_pairs) / max(total_parts, 1)
    has_pairs = pair_ratio >= 0.3  # 30% threshold
    
    # Get labels that appear multiple times (true labels, not random)
    detected_labels = {label for label, count in label_counts.items() if count >= 2}
    
    return has_pairs, detected_labels


def build_hyphen_protection_pattern(detected_labels=None):
    """
    Build comprehensive hyphen protection pattern.

    Args:
        detected_labels: Optional set of detected label tokens for label-value pairs

    Returns:
        str: Pattern for use in re.split()
    """
    # Start with base scientific protection patterns
    base_patterns = [f"(?:{p})" for p in PROTECTED_HYPHEN_PATTERNS]
    base_pattern = f"-(?!{'|'.join(base_patterns)})"

    # If label-value pairs detected, remove labels as separators
    if detected_labels:
        label_parts = sorted(detected_labels)
        if label_parts:
            label_alternation = "|".join(re.escape(l) for l in label_parts)
            label_pattern = rf"(?:^|-)(?:{label_alternation})-"
            return f"(?:{label_pattern}|{base_pattern})"

    # No label-value pairs, use base pattern
    return base_pattern


def regex_for_separators(separators, filenames=None):
    """
    Generate regex pattern with intelligent hyphen protection.
    
    Args:
        separators: Characters to use as separators (string or list)
        filenames: Optional list of filenames for intelligent pattern detection
    
    Returns:
        str: Regex pattern suitable for re.split()
    """
    tokens = []
    has_whitespace = False
    detected_labels = None
    
    # Detect label-value pairs if filenames provided and hyphen is a separator
    if filenames and '-' in separators:
        has_pairs, detected_labels = detect_label_value_pairs(filenames)
        if not has_pairs:
            detected_labels = None
    
    # Build separator tokens
    for char in separators:
        if char.isspace():
            has_whitespace = True
        elif char == "-":
            # Use intelligent pattern for hyphens
            hyphen_pattern = build_hyphen_protection_pattern(detected_labels)
            tokens.append(hyphen_pattern)
        else:
            tokens.append(re.escape(char))
    
    if has_whitespace:
        tokens.append(r"\s")
    
    if not tokens:
        return r"(?<=\D)(?=\d)|(?<=\d)(?=\D)"
    
    # Combine all separator patterns
    return "(?:" + "|".join(tokens) + ")+"


def suggest_separator_regex(filenames, allowed_separators=None):
    counts = Counter()
    for name in filenames:
        base = extract_base_name(name)
        for char in base:
            if allowed_separators is None:
                if not char.isalnum():
                    counts[char] += 1
            elif char in allowed_separators:
                counts[char] += 1

    if not counts:
        return regex_for_separators([], filenames=filenames)

    top = counts.most_common()
    max_count = top[0][1]
    candidates = [char for char, count in top if count >= max_count * 0.4]

    return regex_for_separators(candidates[:5], filenames=filenames)
