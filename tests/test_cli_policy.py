from unittest.mock import patch

from cli.policy import run_policy_recommend


def test_run_policy_recommend_invokes_runner(tmp_path, capsys):
    themes_path = tmp_path / "t.yaml"
    themes_path.write_text(
        "themes:\n  T:\n    keywords: [k]\n    sectors: [s]\n    funds: []\n", encoding="utf-8",
    )

    with patch("cli.policy.PolicyScreenerRunner") as MockRunner, \
         patch("cli.policy.build_llm", return_value=None):
        instance = MockRunner.return_value
        instance.run.return_value = "# 报告"

        run_policy_recommend(
            themes=["T"], date="2026-06-18", deep=False,
            config_overrides={"policy_themes_file": str(themes_path)},
        )

        instance.run.assert_called_once()
        out = capsys.readouterr().out
        assert "报告" in out