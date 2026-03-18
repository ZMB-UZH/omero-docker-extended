from __future__ import annotations

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


class InstallTranscriptRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.helper_path = cls.repo_root / "installation" / "install_transcript_utils.sh"

    def test_transcript_helper_saves_preinstall_and_install_output_under_omero_data_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            data_dir = temp_root / "omero_data"
            env_file = temp_root / "installation_paths.env"
            fake_script = temp_root / "fake_pull.sh"

            env_file.write_text(
                textwrap.dedent(
                    f"""\
                    OMERO_INSTALLATION_PATH={temp_root}
                    OMERO_DATA_PATH={data_dir}
                    """
                ),
                encoding="utf-8",
            )

            fake_script.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    # shellcheck disable=SC1091
                    . {self.helper_path}
                    install_transcript_enable "{env_file}" "$0" "$@"
                    echo "pre-install output"
                    install_transcript_publish_final_path_if_needed "fake_pull" "{env_file}" "{data_dir}"
                    echo "install output"
                    """
                ),
                encoding="utf-8",
            )
            fake_script.chmod(0o755)

            result = subprocess.run(
                ["bash", str(fake_script)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            transcript_dir = data_dir / "installation_logs"
            transcripts = sorted(transcript_dir.glob("fake_pull_*.log"))
            self.assertEqual(1, len(transcripts))
            transcript_text = transcripts[0].read_text(encoding="utf-8")

            self.assertIn("pre-install output", transcript_text)
            self.assertIn("install output", transcript_text)
            self.assertIn(
                f"Installation transcript will be saved to: {transcripts[0]}",
                transcript_text,
            )
            self.assertIn("Saved installation transcript:", result.stdout)


if __name__ == "__main__":
    unittest.main()
