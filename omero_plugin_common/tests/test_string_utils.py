from __future__ import annotations

from omero_plugin_common import string_utils


def test_snake_to_camel_converts_multiword_names() -> None:
    assert string_utils.snake_to_camel("alpha_beta_gamma") == "alphaBetaGamma"
    assert string_utils.snake_to_camel("single") == "single"


def test_build_message_payload_uses_special_confirm_key_and_camel_cases_others() -> None:
    payload = string_utils.build_message_payload(
        ["confirm_irreversible_action", "retry_upload_job"],
        {
            "confirm_irreversible_action": lambda: "Proceed?",
            "retry_upload_job": lambda: "Retry the upload?",
        },
    )

    assert payload == {
        "confirmIrreversible": "Proceed?",
        "retryUploadJob": "Retry the upload?",
    }
