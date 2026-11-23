"""内容保真度门的回归测试：判据来自 ai-club 54 篇逐篇核读的反例。

每个判据都配「已知违规必红 + 已知正例必绿 + 注入反证翻面」，门能失败才算有效。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from eval_gate.content_audit import (
    byte_contains,
    cross_byline,
    detect_fidelity,
    detect_redirect,
    selftest,
)


class RedirectTests(unittest.TestCase):
    def test_verge_and_ars_are_redirects(self):
        self.assertTrue(detect_redirect("News. Read the full story at The Verge")["is_redirect"])
        self.assertTrue(detect_redirect("Read full article\n\nComments")["is_redirect"])

    def test_batch03_false_positives_are_green(self):
        # 批次03 初版检测器把这三篇尾误判为截断
        for tail in ["bridge. License MIT",
                     "periods. ↩︎ See our calculations ↩︎",
                     "contact x. Vipul Ved Prakash CEO",
                     "thanks for reading, keep those hammers up"]:
            with self.subTest(tail=tail):
                self.assertFalse(detect_redirect(tail)["is_redirect"])

    def test_tail_no_punct_is_not_conclusive(self):
        # 无标点但正当收尾不能单独判红
        r = detect_redirect("...news hot card. 相关阅读")
        self.assertFalse(r["is_redirect"])
        self.assertFalse(r["tail_suspicious_not_conclusive"])


class FidelityTests(unittest.TestCase):
    def test_0999_with_glob_swallowed_is_red(self):
        # blog/65566：相似度 ~0.999 但 ** 被吞让 podspec glob 失效
        r = detect_fidelity("Classes/**/*", "Classes//*")
        self.assertFalse(r["fidelity_ok"])
        self.assertGreaterEqual(r["functional_diff_count"], 1)

    def test_pure_whitespace_is_green(self):
        self.assertTrue(detect_fidelity("a b c", "a  b   c")["fidelity_ok"])

    def test_mutation_restoring_glob_flips_green(self):
        self.assertTrue(detect_fidelity("Classes/**/*", "Classes/**/*")["fidelity_ok"])

    def test_actual_article_pair_is_red(self):
        # 真实样本：blog/65566 的 source_files / public_header_files 两处
        src = "s.source_files='podsName/Classes/**/*';s.public_header_files='Pod/Classes/**/*.h'"
        dst = "s.source_files='podsName/Classes//*';s.public_header_files='Pod/Classes//*.h'"
        r = detect_fidelity(src, dst)
        self.assertFalse(r["fidelity_ok"])
        # `**` 被当 markdown 加粗吞掉 → 字符数减少，ratio < 1
        self.assertLess(r["ratio"], 1.0)
        self.assertGreater(r["ratio"], 0.95)  # 但仍是「看起来几乎一样」的高相似


class ByteLayerTests(unittest.TestCase):
    def test_byte_contains_finds_literal(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            p.write_bytes(b"mailto:real-address@example.com")
            self.assertTrue(byte_contains(p, "mailto:"))
            self.assertTrue(byte_contains(p, "@example.com"))

    def test_byte_contains_rejects_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            p.write_bytes(b"nothing here")
            self.assertFalse(byte_contains(p, "NOT_THERE"))

    def test_mutation_removing_literal_flips_red(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"
            p.write_bytes(b"mailto:real@example.com")
            self.assertTrue(byte_contains(p, "mailto:"))
            p.write_bytes(b"contact: real@example.com")  # 注入违规：删掉 mailto:
            self.assertFalse(byte_contains(p, "mailto:"))


class BylineTests(unittest.TestCase):
    def test_conflict_flagged(self):
        c = cross_byline("AI Club", "Hacker News", ["Vipul Ved Prakash"])
        self.assertTrue(c["conflict"])

    def test_same_author_not_flagged(self):
        self.assertFalse(cross_byline("Vipul Ved Prakash", "Hacker News", ["Vipul Ved Prakash"])["conflict"])


class SelftestTests(unittest.TestCase):
    def test_module_selftest_all_pass(self):
        self.assertEqual(selftest(), 0)


if __name__ == "__main__":
    unittest.main()
