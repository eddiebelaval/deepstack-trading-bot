"""
Tests for config validation — AnalysisConfig, profile name safety, bounds.

Covers:
- AnalysisConfig parsed from YAML section correctly
- AnalysisConfig uses safe defaults when section is missing
- Profile name validation rejects path traversal strings
- Profile name validation accepts valid names
- AnalysisConfig field bounds enforced by Pydantic
"""

import pytest
from pydantic import ValidationError

from kalshi_trader.config import (
    AnalysisConfig,
    YAMLConfig,
    load_profile,
)


# ── AnalysisConfig parsing ───────────────────────────────────────────


class TestAnalysisConfigParsing:
    def test_analysis_config_from_yaml(self):
        """YAML analysis section should parse into AnalysisConfig."""
        yaml_data = {
            "analysis": {
                "enabled": True,
                "model": "claude-sonnet-4-5-20250929",
                "auto_apply_kelly": False,
                "min_trades_for_analysis": 20,
            }
        }
        config = YAMLConfig(**yaml_data)
        assert config.analysis.enabled is True
        assert config.analysis.model == "claude-sonnet-4-5-20250929"
        assert config.analysis.auto_apply_kelly is False
        assert config.analysis.min_trades_for_analysis == 20

    def test_analysis_config_defaults(self):
        """Missing analysis section should use safe defaults."""
        config = YAMLConfig()
        assert config.analysis.enabled is False
        assert config.analysis.auto_apply_kelly is True
        assert config.analysis.min_trades_for_analysis == 10

    def test_analysis_config_standalone_defaults(self):
        """AnalysisConfig created directly should have safe defaults."""
        cfg = AnalysisConfig()
        assert cfg.enabled is False
        assert cfg.model == "claude-sonnet-4-5-20250929"
        assert cfg.auto_apply_params is False

    def test_min_trades_too_low_rejected(self):
        """min_trades_for_analysis below 5 should fail validation."""
        with pytest.raises(ValidationError):
            AnalysisConfig(min_trades_for_analysis=1)

    def test_min_trades_too_high_rejected(self):
        """min_trades_for_analysis above 100 should fail validation."""
        with pytest.raises(ValidationError):
            AnalysisConfig(min_trades_for_analysis=500)

    def test_min_trades_boundary_values(self):
        """Boundary values 5 and 100 should be accepted."""
        low = AnalysisConfig(min_trades_for_analysis=5)
        high = AnalysisConfig(min_trades_for_analysis=100)
        assert low.min_trades_for_analysis == 5
        assert high.min_trades_for_analysis == 100


# ── Profile name validation ──────────────────────────────────────────


class TestProfileNameValidation:
    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            load_profile("../../etc/passwd")

    def test_dotdot_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            load_profile("../secrets")

    def test_slash_in_name_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            load_profile("profiles/hidden")

    def test_space_in_name_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            load_profile("my profile")

    def test_valid_alphanumeric_passes(self):
        """Valid names should not raise (may return empty dict if file missing)."""
        result = load_profile("aggressive")
        assert isinstance(result, dict)

    def test_valid_with_hyphen_passes(self):
        result = load_profile("my-profile")
        assert isinstance(result, dict)

    def test_valid_with_underscore_passes(self):
        result = load_profile("my_profile_v2")
        assert isinstance(result, dict)

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            load_profile("")
