from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import headline_pipeline as hlp
import headline_scoring as hls
import transcribe_segments as ts


class HeadlineQualityModuleTests(unittest.TestCase):
    def test_source_quality_strategy_for_accepted_source(self):
        validation = hlp.SourceValidationResult(
            accepted=True,
            reasons=[],
            content_word_count=4,
            subject_hint_count=1,
            action_hint_count=1,
            unknown_ratio=0.0,
        )
        self.assertEqual(hlp.compute_source_quality_penalty(validation), 0.0)
        self.assertEqual(
            hlp.decide_headline_generation_strategy(validation),
            ("llm_ranked", "high", 0.0),
        )

    def test_source_quality_strategy_for_soft_and_severe_sources(self):
        soft = hlp.SourceValidationResult(
            accepted=False,
            reasons=["missing_subject_hint", "incomplete_sentence"],
            content_word_count=2,
            subject_hint_count=0,
            action_hint_count=1,
            unknown_ratio=0.1,
        )
        self.assertEqual(hlp.compute_source_quality_penalty(soft), 1.6)
        self.assertEqual(
            hlp.decide_headline_generation_strategy(soft),
            ("weak_llm", "medium", 1.6),
        )

        severe = hlp.SourceValidationResult(
            accepted=False,
            reasons=["empty_source", "too_many_unknown_tokens"],
            content_word_count=0,
            subject_hint_count=0,
            action_hint_count=0,
            unknown_ratio=1.0,
        )
        self.assertAlmostEqual(hlp.compute_source_quality_penalty(severe), 3.8)
        self.assertEqual(
            hlp.decide_headline_generation_strategy(severe),
            ("fallback_extractive", "low", 3.8),
        )
        self.assertFalse(hlp.should_skip_headline_generation("", severe))

    def test_confidence_thresholds_and_compatibility_aliases(self):
        self.assertEqual(hls.headline_confidence_label(score_total=8.0, candidate_confidence=1.0), "high")
        self.assertEqual(hls.headline_confidence_label(score_total=4.0, candidate_confidence=0.5), "medium")
        self.assertEqual(hls.headline_confidence_label(score_total=2.0, candidate_confidence=0.5, penalty=2.0), "low")
        self.assertIs(ts.SourceValidationResult, hlp.SourceValidationResult)
        self.assertIs(ts.compute_source_quality_penalty, hlp.compute_source_quality_penalty)
        self.assertIs(ts.decide_headline_generation_strategy, hlp.decide_headline_generation_strategy)
        self.assertIs(ts.headline_confidence_label, hls.headline_confidence_label)


if __name__ == "__main__":
    unittest.main()
