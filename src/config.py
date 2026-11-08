from __future__ import annotations

import os

# Provisional operating thresholds. Calibrate against a manually labelled set before production use.
HIGH_SCORE_THRESHOLD = float(os.getenv("PROMOBRIDGE_HIGH_SCORE_THRESHOLD", "0.82"))
LOW_SCORE_THRESHOLD = float(os.getenv("PROMOBRIDGE_LOW_SCORE_THRESHOLD", "0.60"))
MIN_TOP_TWO_MARGIN = float(os.getenv("PROMOBRIDGE_MIN_MARGIN", "0.08"))
MIN_MEANINGFUL_TOKENS = int(os.getenv("PROMOBRIDGE_MIN_TOKENS", "4"))
