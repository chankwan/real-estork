"""
RealEstork — Classification Pipeline
Module 2 (M2) — YAML-driven rule-based classifier + AI signal integration

Architecture: Rule-based foundation (fast, deterministic) + AI supplement (~15%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from pipeline.signals import SIGNAL_FUNCTIONS, SignalContext

# Per-source scoring overrides. Any source listed here will auto-load
# config/scoring_{source}.yaml if the file exists (falls back to default otherwise).
PER_SOURCE_CONFIGS: tuple[str, ...] = ("batdongsan", "muaban")

# Classification labels
LABEL_CHINH_CHU = "chinh_chu"
LABEL_CAN_XAC_MINH = "can_xac_minh"
LABEL_MOI_GIOI = "moi_gioi"


@dataclass
class ClassificationResult:
    """Full classification result for one listing."""
    score: int                              # 0-100
    label: str                              # chinh_chu / can_xac_minh / moi_gioi
    signals_fired: dict[str, float] = field(default_factory=dict)
    # key: signal_name → contribution (weight Applied)
    # Positive = boosted toward chính chủ, negative = toward môi giới
    ai_probability: float | None = None
    ai_reasoning: str = ""


class ClassificationPipeline:
    """
    YAML-driven classification pipeline.
    
    Rules: loaded from config/scoring.yaml
    AI signal: integrated as 1 of ~15 signals
    Config changes: edit YAML → restart scheduler (no redeploy)
    """

    def __init__(self, config_path: str = "config/scoring.yaml") -> None:
        self._default_path = config_path
        self._configs: dict[str, dict[str, Any]] = {}  # key: source or "_default"
        self._load_config(config_path)

    def _load_yaml(self, path: str) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_config(self, config_path: str) -> None:
        """Load default scoring config + per-source overrides (if present)."""
        default = self._load_yaml(config_path)
        self._configs["_default"] = default

        # Expose defaults as instance attrs for backward compat (callers reading e.g.
        # classifier.threshold_chinh_chu or .alert_filters still work).
        self.threshold_chinh_chu: int = default.get("threshold_chinh_chu", 65)
        self.threshold_can_xac_minh: int = default.get("threshold_can_xac_minh", 40)
        self.base_score: int = default.get("base_score", 50)
        self.signals_config: dict[str, Any] = default.get("signals", {})
        self.alert_filters: dict[str, Any] = default.get("alert_filters", {})

        logger.info(
            f"[classifier] Loaded default: {len(self.signals_config)} signals. "
            f"Thresholds: chinh_chu>={self.threshold_chinh_chu}, "
            f"can_xac_minh>={self.threshold_can_xac_minh}"
        )

        # Per-source overrides
        for source in PER_SOURCE_CONFIGS:
            path = Path(f"config/scoring_{source}.yaml")
            if path.exists():
                cfg = self._load_yaml(str(path))
                self._configs[source] = cfg
                logger.info(
                    f"[classifier] Loaded {source}: {len(cfg.get('signals', {}))} signals. "
                    f"Thresholds: chinh_chu>={cfg.get('threshold_chinh_chu', '?')}, "
                    f"can_xac_minh>={cfg.get('threshold_can_xac_minh', '?')}"
                )
            else:
                logger.debug(f"[classifier] No per-source config for '{source}' at {path}")

    def _config_for(self, source: str | None) -> dict[str, Any]:
        """Return the scoring config dict for a given source, with default fallback."""
        if source and source in self._configs:
            return self._configs[source]
        return self._configs["_default"]

    def classify(
        self,
        listing: Any,  # RawListing
        phone_stats: dict[str, Any] | None = None,
        ai_result: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        """
        Classify a listing. Returns ClassificationResult.
        
        Args:
            listing: RawListing instance
            phone_stats: Phone frequency data from DB (optional)
            ai_result: AI classification output dict (optional, async supplement)
        """
        # Pick config (per-source override if present)
        source = getattr(listing, "source", None)
        config = self._config_for(source)
        base_score = config.get("base_score", 50)
        signals_config = config.get("signals", {})
        th_chinh_chu = config.get("threshold_chinh_chu", 65)
        th_can_xac_minh = config.get("threshold_can_xac_minh", 40)

        # Build signal context
        ctx = SignalContext.from_listing(listing, phone_stats)

        # Inject AI result if available
        if ai_result and isinstance(ai_result, dict):
            ctx.ai_owner_probability = ai_result.get("is_owner_probability")

        # Run all rule-based signals
        score = base_score
        signals_fired: dict[str, float] = {}

        for signal_name, signal_config in signals_config.items():
            if not isinstance(signal_config, dict):
                continue  # Skip non-signal entries (e.g., listing_age_filter_default)

            weight = signal_config.get("weight", 0)
            if weight == 0:
                continue

            check_fn = SIGNAL_FUNCTIONS.get(signal_name)
            if check_fn is None:
                logger.warning(f"[classifier] No function for signal '{signal_name}'")
                continue

            try:
                result = check_fn(ctx)
            except Exception as e:
                logger.error(f"[classifier] Signal '{signal_name}' error: {e}")
                continue

            # Apply weight
            if signal_name == "ai_classification":
                # AI signal: result is float 0.0-1.0, scale weight
                # probability=1.0 → +weight, probability=0.0 → -weight, 0.5 → 0
                contribution = weight * (result - 0.5) * 2
            elif result:
                contribution = weight
            else:
                contribution = 0

            if contribution != 0:
                signals_fired[signal_name] = contribution
                score += contribution

        # Clamp score 0-100
        score = max(0, min(100, round(score)))

        # Determine label using source-specific thresholds
        if score >= th_chinh_chu:
            label = LABEL_CHINH_CHU
        elif score >= th_can_xac_minh:
            label = LABEL_CAN_XAC_MINH
        else:
            label = LABEL_MOI_GIOI

        return ClassificationResult(
            score=score,
            label=label,
            signals_fired=signals_fired,
            ai_probability=ctx.ai_owner_probability,
            ai_reasoning=ai_result.get("reasoning", "") if ai_result else "",
        )

    def label(self, score: int) -> str:
        """Convert score to label string."""
        if score >= self.threshold_chinh_chu:
            return LABEL_CHINH_CHU
        elif score >= self.threshold_can_xac_minh:
            return LABEL_CAN_XAC_MINH
        return LABEL_MOI_GIOI

    def _normalize_district(self, district: str) -> str:
        """Normalize district string for whitelist comparison (ASCII, no prefix)."""
        import re
        from unidecode import unidecode
        
        # Muaban specific: "P. X (Q. Y cũ)" -> extract Q. Y
        if "(" in district and ")" in district:
            inner = re.search(r'\((.*?)\)', district)
            if inner:
                inner_text = inner.group(1)
                if any(k in inner_text for k in ["Q.", "Quận", "H.", "Huyện"]):
                    district = inner_text

        d = unidecode(district or "").lower().strip()
        # Remove common prefixes: "quan ", "q.", "q ", "huyen ", "h.", "thi xa ", "p.", "phuong "
        d = re.sub(r'^(quan|huyen|thi\s*xa|q\.?|h\.?|p\.?|phuong)\s*', '', d)
        # Remove leading zeros: "03" → "3"
        if re.match(r'^\d+$', d):
            d = str(int(d))
        return d.strip()

    def _min_price_for_district(self, filters: dict[str, Any], listing_district: str) -> int:
        """Resolve min price: per-district override (from district_price_overrides) or fallback to wife_min_price_vnd."""
        base = filters.get("wife_min_price_vnd", 0)
        overrides = filters.get("district_price_overrides", {}) or {}
        if not overrides:
            return base
        normalized_listing = self._normalize_district(listing_district or "")
        for d, price in overrides.items():
            if self._normalize_district(d) == normalized_listing:
                return int(price)
        return base

    def _alert_filters_for(self, source: str | None) -> dict[str, Any]:
        """Get alert_filters for source, falling back to default for missing keys."""
        default_filters = self._configs["_default"].get("alert_filters", {})
        if source and source in self._configs:
            source_filters = self._configs[source].get("alert_filters", {})
            # Merge: source overrides win, but default keys fill gaps
            return {**default_filters, **source_filters}
        return default_filters

    def should_alert_wife(self, result: ClassificationResult, listing: Any) -> bool:
        """
        Determine if this listing should be immediately alerted to vợ.
        Applies age filter (default 48h), min score (55), and district whitelist.
        """
        filters = self._alert_filters_for(getattr(listing, "source", None))
        min_score = filters.get("wife_min_score", 55)
        max_age_hours = filters.get("wife_max_listing_age_hours", 48)

        if result.score < min_score:
            return False
        if listing.listing_age_hours is not None and listing.listing_age_hours > max_age_hours:
            return False

        # Price filter (per-district override if matched; else default wife_min_price_vnd)
        min_price = self._min_price_for_district(filters, listing.district or "")
        if min_price and listing.price_vnd_monthly and listing.price_vnd_monthly < min_price:
            return False

        # District whitelist — empty list means allow all
        allowed = filters.get("wife_allowed_districts", [])
        if allowed:
            normalized_allowed = {self._normalize_district(d) for d in allowed}
            listing_district = self._normalize_district(listing.district or "")
            if listing_district not in normalized_allowed:
                logger.debug(
                    f"[classifier] District '{listing.district}' → '{listing_district}' "
                    f"not in whitelist, skipping alert"
                )
                return False

        # Main street filter — opt-in, disabled by default
        if filters.get("wife_main_street_only", False):
            if getattr(listing, "is_main_street", None) is not True:
                logger.debug(f"[classifier] Skipping non-main-street listing {listing.source_id}")
                return False

        return True

    def alert_skip_reason(self, result: ClassificationResult, listing: Any) -> str:
        """
        Return the reason this listing would NOT be alerted, or '' if it would be sent.
        Mirrors should_alert_wife() but returns a string reason for logging.
        """
        filters = self._alert_filters_for(getattr(listing, "source", None))
        min_score = filters.get("wife_min_score", 55)
        max_age_hours = filters.get("wife_max_listing_age_hours", 48)

        if result.score < min_score:
            return result.label  # "moi_gioi" or "can_xac_minh"
        if listing.listing_age_hours is not None and listing.listing_age_hours > max_age_hours:
            return "tin_cu"
        min_price = self._min_price_for_district(filters, listing.district or "")
        if min_price and listing.price_vnd_monthly and listing.price_vnd_monthly < min_price:
            return "gia_thap"
        allowed = filters.get("wife_allowed_districts", [])
        if allowed:
            normalized_allowed = {self._normalize_district(d) for d in allowed}
            if self._normalize_district(listing.district or "") not in normalized_allowed:
                return "ngoai_quan"
        if filters.get("wife_main_street_only", False):
            if getattr(listing, "is_main_street", None) is not True:
                return "pho_phu"
        return ""

    def should_alert_product(self, result: ClassificationResult, listing: Any | None = None) -> bool:
        """Determine if listing should go to Telegram/Discord product feed."""
        source = getattr(listing, "source", None) if listing is not None else None
        filters = self._alert_filters_for(source)
        min_score = filters.get("product_min_score", 65)
        return result.score >= min_score

    def reload_config(self, config_path: str = "config/scoring.yaml") -> None:
        """Hot-reload config (call after editing scoring.yaml)."""
        self._load_config(config_path)
        logger.info("[classifier] Config reloaded successfully")

    def analyze_feedback(self, feedback_rows: list[dict]) -> dict[str, Any]:
        """
        Analyze labeled feedback to compute per-signal accuracy.
        Returns dict with accuracy stats and weight adjustment suggestions.
        """
        if not feedback_rows:
            return {"accuracy": 0, "signal_report": "No feedback yet", "suggestions": ""}

        total = len(feedback_rows)
        correct = sum(
            1 for row in feedback_rows
            if row.get("predicted_label") == row.get("actual_label")
        )
        accuracy = round((correct / total) * 100, 1) if total > 0 else 0

        # Per-signal analysis
        signal_stats: dict[str, dict] = {}
        for row in feedback_rows:
            signals = row.get("signals_at_prediction", {}) or {}
            actual = row.get("actual_label", "")
            for sig_name, contribution in signals.items():
                if sig_name not in signal_stats:
                    signal_stats[sig_name] = {"correct_direction": 0, "wrong_direction": 0}
                # Signal was correct if contribution sign matches actual label direction
                was_helpful = (
                    (contribution > 0 and actual == LABEL_CHINH_CHU) or
                    (contribution < 0 and actual == LABEL_MOI_GIOI)
                )
                if was_helpful:
                    signal_stats[sig_name]["correct_direction"] += 1
                else:
                    signal_stats[sig_name]["wrong_direction"] += 1

        # Build signal report
        report_lines = []
        suggestions = []
        for sig_name, stats in sorted(signal_stats.items()):
            total_fires = stats["correct_direction"] + stats["wrong_direction"]
            if total_fires == 0:
                continue
            acc = round(stats["correct_direction"] / total_fires * 100)
            report_lines.append(f"  {sig_name}: {acc}% accuracy ({total_fires} fires)")
            if acc < 50:
                current_weight = self.signals_config.get(sig_name, {}).get("weight", 0)
                suggestions.append(
                    f"  Consider reducing weight of '{sig_name}' (currently {current_weight}, accuracy {acc}%)"
                )

        return {
            "accuracy": accuracy,
            "total_samples": total,
            "signal_report": "\n".join(report_lines) or "No signals fired",
            "suggestions": "\n".join(suggestions) or "All signals healthy",
        }
