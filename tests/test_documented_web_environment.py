"""Keep documented OMERO properties aligned with the installation contract."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_documented_web_properties_map_to_supported_example_keys() -> None:
    """Inputs: property table and example. Output: exact, supported environment mappings."""
    guide = (ROOT / "docs/reference/ai-agent-runtime-playbook.md").read_text()
    example = (ROOT / "env/omeroweb_example.env").read_text()
    mappings = re.findall(
        r"^\|\s*`(omero\.web\.[^`\n]+)`\s*\|\s*`(CONFIG_omero_web_[^`\n]+)`\s*\|",
        guide,
        re.MULTILINE,
    )
    keys = set(
        re.findall(r"^(?:#\s*)?(CONFIG_[A-Za-z0-9_]+)\s*=", example, re.MULTILINE)
    )
    assert mappings, "The guide must retain its property translation table"
    assert keys, "The canonical example must declare supported web settings"
    for property_name, variable in mappings:
        assert variable == "CONFIG_" + property_name.replace("_", "__").replace(
            ".", "_"
        )
        assert variable in keys, (
            f"Documented setting is absent from the example: {variable}"
        )
