import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import transcribe_segments as ts


class HeadlineFallbackTests(unittest.TestCase):
    def test_tag_fallbacks_are_publishable(self):
        cases = {
            "好プレー": "好プレーで盛り上がる",
            "おめ": "祝福コメントが集まる",
            "ホラー": "緊張の展開にざわつく",
            "まずい": "予想外の展開に驚く",
            "ww": "笑いが一気に広がる",
        }
        for tag, expected in cases.items():
            with self.subTest(tag=tag):
                headline = ts.build_tag_based_fallback_headline([tag])
                self.assertEqual(headline, expected)
                self.assertTrue(ts.validate_final_headline_japanese(headline).accepted)

    def test_broken_or_verbatim_headlines_are_not_publishable(self):
        rejected = (
            "いや",
            "すすみませ",
            "アドレス",
            "はい",
            "起点ってい",
            "100万回感謝をするっていう",
            "昨日はちょっと老犬の介護に行ってましたいやまぁ結構ね長生",
            "あーもうなんでフルリモート終わったのこの世界勘弁して",
            "いやに注目が集まる",
            "すすみませに注目が集まる",
            "アドレスに注目が集まる",
            "はいに注目が集まる",
            "起点っていに注目が集まる",
            "なんで?商人がある",
            "はい?エンジェルナンバー",
        )
        for headline in rejected:
            with self.subTest(headline=headline):
                self.assertFalse(ts.is_publishable_headline(headline))

    def test_invalid_extractive_fallback_is_replaced_by_tag_fallback(self):
        target = ts.SegmentTarget(
            video={"title": ""},
            item={"tags": ["ホラー"]},
            start_sec=0,
            end_sec=60,
            needs_transcript=False,
            needs_headline=True,
        )
        outcome = ts.HeadlineGenerationOutcome(
            headline=ts.HeadlineResult(
                text="いや",
                model="test",
                source="test",
            ),
            generation_reason="test",
        )

        result = ts._apply_headline_post_filter_fallback(
            target,
            label="test",
            outcome=outcome,
            headline_source_config=ts.HEADLINE_SOURCE_CONFIG,
            transcript_text="",
            prepared_source_text="",
        )

        self.assertEqual(result.headline.text, "緊張の展開にざわつく")
        self.assertEqual(result.headline.generation_mode, "fallback_tag")
        self.assertTrue(ts.validate_final_headline_japanese(result.headline.text).accepted)


if __name__ == "__main__":
    unittest.main()
