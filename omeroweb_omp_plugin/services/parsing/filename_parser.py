"""
Filename parsing logic.
"""
import re
import logging

logger = logging.getLogger(__name__)


def parse_filename(filename, sep_pattern):
    """
    Parse filename into parts using separator pattern.
    
    Args:
        filename: Image filename to parse
        sep_pattern: Regular expression pattern for separator
        
    Returns:
        List of parsed parts
    """
    m = re.search(r"\[(.+?)\]", filename)
    if m:
        base_name = m.group(1)
    else:
        f = filename.replace("\t", " ")
        m2 = re.search(r".*\s+(.+?)\s*$", f)
        if m2:
            base_name = m2.group(1).rsplit(".", 1)[0]
        else:
            base_name = filename.rsplit(".", 1)[0]

    parts = [p for p in re.split(sep_pattern, base_name) if p]
    return parts
