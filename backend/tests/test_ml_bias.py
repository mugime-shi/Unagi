"""
Tests for the hourly bias correction (LGBM_BIAS_CORRECTION).

Covers the pure helpers only — no LightGBM training:
- _hourly_bias: shrinkage math, clipping, empty validation set
- _active_bias_qhat: env-flag gating and legacy cache dicts
"""

import numpy as np
import pytest

from app.services.ml_forecast_service import _active_bias_qhat, _hourly_bias


def _val_set(residual_by_hour, n_per_hour=30, base_pred=1.0):
    """Build (y_val, val_preds, hours) with a fixed residual per hour of day."""
    hours = np.repeat(np.arange(24), n_per_hour).astype(float)
    val_preds = np.full(len(hours), base_pred)
    y_val = val_preds + np.array([residual_by_hour[int(h)] for h in hours])
    return y_val, val_preds, hours


class TestHourlyBias:
    def test_shrinkage_exact(self):
        """Constant residual 0.1, n=30, k=10 → 0.1 * 30/40 = 0.075."""
        y_val, val_preds, hours = _val_set([0.1] * 24)
        bias = _hourly_bias(y_val, val_preds, hours, shrink_k=10.0, clip=0.15)
        assert bias == [pytest.approx(0.075)] * 24

    def test_clip_positive_and_negative(self):
        """Residual ±0.5 shrinks to ±0.375, then clips to ±0.15."""
        residuals = [0.5] * 12 + [-0.5] * 12
        y_val, val_preds, hours = _val_set(residuals)
        bias = _hourly_bias(y_val, val_preds, hours, shrink_k=10.0, clip=0.15)
        assert bias[:12] == [pytest.approx(0.15)] * 12
        assert bias[12:] == [pytest.approx(-0.15)] * 12

    def test_empty_validation_set(self):
        empty = np.array([])
        assert _hourly_bias(empty, empty, empty) == [0.0] * 24

    def test_missing_hours_stay_zero(self):
        """Hours absent from the validation set keep bias 0."""
        hours = np.array([4.0] * 30)
        val_preds = np.full(30, 1.0)
        y_val = val_preds + 0.1
        bias = _hourly_bias(y_val, val_preds, hours)
        assert bias[4] == pytest.approx(0.075)
        assert all(bias[h] == 0.0 for h in range(24) if h != 4)

    def test_thin_sample_shrinks_harder(self):
        """n=5 with k=10 → factor 5/15 = 1/3."""
        hours = np.array([0.0] * 5)
        val_preds = np.full(5, 1.0)
        y_val = val_preds + 0.09
        bias = _hourly_bias(y_val, val_preds, hours, shrink_k=10.0)
        assert bias[0] == pytest.approx(0.03)


class TestActiveBiasQhat:
    MODELS = {"q_hat": 0.2, "bias": [0.05] * 24, "q_hat_bias": 0.18}

    def test_flag_off_is_noop(self, monkeypatch):
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        bias, q_hat = _active_bias_qhat(self.MODELS, "SE4")
        assert bias is None
        assert q_hat == 0.2

    def test_flag_on_returns_bias_and_qhat_bias(self, monkeypatch):
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "1")
        bias, q_hat = _active_bias_qhat(self.MODELS, "SE4")
        assert bias is not None
        assert list(bias) == [0.05] * 24
        assert q_hat == 0.18

    def test_flag_on_legacy_dict_without_bias(self, monkeypatch):
        """Pre-v9 cache dicts have no 'bias' → no-op even with the flag on."""
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "1")
        bias, q_hat = _active_bias_qhat({"q_hat": 0.2}, "SE4")
        assert bias is None
        assert q_hat == 0.2

    def test_flag_on_all_zero_bias_is_noop(self, monkeypatch):
        """No-validation-set models store zeros → treated as absent."""
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "1")
        bias, q_hat = _active_bias_qhat({"q_hat": 0.2, "bias": [0.0] * 24, "q_hat_bias": 0.0}, "SE4")
        assert bias is None
        assert q_hat == 0.2

    def test_flag_on_missing_qhat_bias_falls_back(self, monkeypatch):
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "1")
        bias, q_hat = _active_bias_qhat({"q_hat": 0.2, "bias": [0.05] * 24}, "SE4")
        assert bias is not None
        assert q_hat == 0.2

    def test_area_list_enables_only_listed_areas(self, monkeypatch):
        """LGBM_BIAS_CORRECTION=SE3,SE4 applies to those areas only."""
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "SE3,SE4")
        for area, expect_on in [("SE1", False), ("SE2", False), ("SE3", True), ("SE4", True)]:
            bias, q_hat = _active_bias_qhat(self.MODELS, area)
            if expect_on:
                assert bias is not None, area
                assert q_hat == 0.18
            else:
                assert bias is None, area
                assert q_hat == 0.2

    def test_area_list_tolerates_spaces_and_case(self, monkeypatch):
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", " se3 , SE4 ")
        bias, _ = _active_bias_qhat(self.MODELS, "SE3")
        assert bias is not None

    def test_all_keyword(self, monkeypatch):
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "all")
        bias, _ = _active_bias_qhat(self.MODELS, "SE1")
        assert bias is not None

    def test_empty_flag_is_off(self, monkeypatch):
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "")
        bias, _ = _active_bias_qhat(self.MODELS, "SE4")
        assert bias is None


class TestCqrAlphaOverride:
    """LGBM_CQR_ALPHA re-quantiles q_hat from stored conformal scores."""

    # 100 scores 0.01..1.00 → quantile((1-α)(1+1/100)) is easy to reason about
    SCORES = [round(0.01 * i, 4) for i in range(1, 101)]
    MODELS = {
        "q_hat": 0.5,
        "bias": [0.05] * 24,
        "q_hat_bias": 0.55,
        "cqr_scores": SCORES,
        "cqr_scores_bias": [s + 0.1 for s in SCORES],
    }

    def test_no_flag_keeps_default_qhat(self, monkeypatch):
        monkeypatch.delenv("LGBM_CQR_ALPHA", raising=False)
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        _, q_hat = _active_bias_qhat(self.MODELS, "SE4")
        assert q_hat == 0.5

    def test_alpha_widens_interval(self, monkeypatch):
        """Smaller alpha → higher quantile of scores → larger q_hat."""
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.10")
        _, q_hat_10 = _active_bias_qhat(self.MODELS, "SE4")
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.30")
        _, q_hat_30 = _active_bias_qhat(self.MODELS, "SE4")
        assert q_hat_10 > q_hat_30

    def test_alpha_applies_only_to_listed_area(self, monkeypatch):
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.10")
        _, q_hat_se3 = _active_bias_qhat(self.MODELS, "SE3")
        assert q_hat_se3 == 0.5

    def test_alpha_uses_bias_scores_when_bias_active(self, monkeypatch):
        """With bias on, re-quantile from cqr_scores_bias (shifted by +0.1 here)."""
        monkeypatch.setenv("LGBM_BIAS_CORRECTION", "SE4")
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.20")
        _, q_hat_on = _active_bias_qhat(self.MODELS, "SE4")
        monkeypatch.delenv("LGBM_BIAS_CORRECTION")
        _, q_hat_off = _active_bias_qhat(self.MODELS, "SE4")
        assert q_hat_on == pytest.approx(q_hat_off + 0.1)

    def test_alpha_default_recovers_stored_qhat_formula(self, monkeypatch):
        """α=0.20 on the raw scores equals the training-time computation."""
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.20")
        _, q_hat = _active_bias_qhat(self.MODELS, "SE4")
        n = len(self.SCORES)
        expected = float(np.quantile(np.array(self.SCORES), min(1.0, 0.8 * (1 + 1 / n))))
        assert q_hat == pytest.approx(expected)

    def test_invalid_values_ignored(self, monkeypatch):
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        for bad in ("SE4:abc", "SE4:0", "SE4:1.5", "garbage"):
            monkeypatch.setenv("LGBM_CQR_ALPHA", bad)
            _, q_hat = _active_bias_qhat(self.MODELS, "SE4")
            assert q_hat == 0.5, bad

    def test_legacy_dict_without_scores_is_noop(self, monkeypatch):
        monkeypatch.delenv("LGBM_BIAS_CORRECTION", raising=False)
        monkeypatch.setenv("LGBM_CQR_ALPHA", "SE4:0.10")
        _, q_hat = _active_bias_qhat({"q_hat": 0.5}, "SE4")
        assert q_hat == 0.5
