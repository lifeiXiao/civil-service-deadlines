import copy
import unittest
from unittest.mock import patch

from scripts.parser import Page, date_tokens, extract_events, is_notice, trusted_url
from scripts.update import apply_overrides, merge_notices
from scripts.common import load
from scripts.build import validate


class ExtractionTests(unittest.TestCase):
    def test_range_inherits_month_year_and_keeps_times(self):
        events = extract_events("报名时间：2026年11月2日9︰00至6日16∶00。", "https://example.gov.cn/a")
        self.assertEqual(events["registration"]["start"], "2026-11-02T09:00:00+08:00")
        self.assertEqual(events["registration"]["end"], "2026-11-06T16:00:00+08:00")

    def test_midnight_rollover(self):
        self.assertEqual(date_tokens("2026年11月6日24:00")[0]["value"], "2026-11-07T00:00:00+08:00")

    def test_date_only_is_not_fabricated_deadline(self):
        event = extract_events("公共科目笔试时间为2026年12月6日。", "https://example.gov.cn/a")["exam"]
        self.assertEqual(event["start"], "2026-12-06")
        self.assertIsNone(event["end"])

    def test_payment_phrase_before_printing_is_not_a_payment_window(self):
        events = extract_events("缴费确认后，报考者可于2026年12月1日9︰00至12月6日14︰15期间下载、打印准考证。", "https://example.gov.cn/a")
        self.assertNotIn("payment", events)
        self.assertEqual(events["admission"]["end"], "2026-12-06T14:15:00+08:00")

    def test_publisher_date_is_not_printing_date(self):
        self.assertEqual(extract_events("准考证打印进入\n某公务员局\n2026年5月18日", "https://example.gov.cn/a"), {})

    def test_later_position_allocation_does_not_replace_exam_registration(self):
        events = extract_events("报考者可在2026年11月1日0:00至11月7日12:00期间登录专题网站进行报名。公开调剂职位报名时间为2027年1月18日9:00至1月20日18:00。", "https://example.gov.cn/a")
        self.assertEqual(events["registration"]["start"], "2026-11-01T00:00:00+08:00")

    def test_registration_and_payment_same_paragraph(self):
        events = extract_events("报名时间：2026年11月3日9:00至11月9日16:00；资格初审时间：2026年11月3日9:00至11月11日16:00；缴费时间：2026年11月3日9:00至11月12日16:00。", "https://example.gov.cn/a")
        self.assertEqual(events["registration"]["end"], "2026-11-09T16:00:00+08:00")
        self.assertEqual(events["payment"]["end"], "2026-11-12T16:00:00+08:00")

    def test_unknown_year_is_not_guessed(self):
        self.assertEqual(extract_events("报名时间：11月1日到11月5日。", "https://example.gov.cn/a"), {})

    def test_postponement_is_not_published_as_original_date(self):
        self.assertEqual(extract_events("报名时间从2026年11月1日至11月5日延期，具体时间另行通知。", "https://example.gov.cn/a"), {})

    def test_birthdate_and_eligibility_are_not_exam_dates(self):
        self.assertEqual(extract_events("年龄：1987年11月1日至2008年11月1日；学历应于2027年9月1日前取得。", "https://example.gov.cn/a"), {})

    def test_scope_and_competition_type(self):
        source = {"id": "beijing", "name": "北京"}
        for title in ("中央机关及其直属机构2027年度考试录用公务员公告", "北京市2027年度公开遴选公务员公告", "北京市2027年度公务员调剂报名公告", "北京市2027年度公务员专业能力测试准考证打印"):
            self.assertFalse(is_notice(title, source, {2027}))
        self.assertTrue(is_notice("北京市各级机关2027年度考试录用公务员公告", source, {2027}))

    def test_links_ignore_embedded_scripts(self):
        page = Page('<script>报名时间2026年1月1日</script><a href="/a"><span>招考公告</span></a>', 'https://example.gov.cn')
        self.assertNotIn("报名时间", page.text)
        self.assertEqual(page.links[0]["url"], "https://example.gov.cn/a")

    def test_official_domain_allowlist(self):
        self.assertTrue(trusted_url("https://rs.example.gov.cn/a", ["example.gov.cn"]))
        for value in ("https://example.gov.cn.evil.com/a", "file:///tmp/a", "http://user:pass@example.gov.cn/a", "http://127.0.0.1/a"):
            self.assertFalse(trusted_url(value, ["example.gov.cn"]))


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.event = {"start": "2026-11-01T09:00:00+08:00", "end": "2026-11-05T18:00:00+08:00", "evidence":"报名时间明确", "source_url":"https://example.gov.cn/a", "verification":"auto"}
        self.exam = {"id":"test-2027", "region_id":"test", "year":2027, "events":{"registration":copy.deepcopy(self.event)}}
        self.notice = {"url":"https://example.gov.cn/b", "region_id":"test", "year":2027, "title":"2027年某省公务员公告", "content_hash":"abc", "review":False, "events":{"registration":copy.deepcopy(self.event)}}

    def test_source_failure_retains_last_known_dates(self):
        result, _ = merge_notices([copy.deepcopy(self.exam)], [], [], "2026-11-17T10:00:00+08:00")
        self.assertEqual(result[0], self.exam)

    def test_conflicting_date_goes_to_review(self):
        self.notice["events"]["registration"]["end"] = "2026-11-07T18:00:00+08:00"
        result, notices = merge_notices([copy.deepcopy(self.exam)], [], [self.notice], "now")
        self.assertEqual(result[0]["events"]["registration"]["end"], self.event["end"])
        self.assertTrue(notices[0]["review"])
        self.assertEqual(len(notices[0]["conflicts"]), 1)

    def test_review_only_notice_does_not_create_record(self):
        self.notice["review"] = True
        result, notices = merge_notices([], [], [self.notice], "now")
        self.assertEqual(result, [])
        self.assertEqual(len(notices), 1)

    def test_unchanged_notice_keeps_first_seen(self):
        _, notices = merge_notices([], [], [self.notice], "first")
        _, notices = merge_notices([], notices, [self.notice], "second")
        self.assertEqual(notices[0]["first_seen_at"], "first")
        self.assertNotIn("changed_at", notices[0])

    def test_manual_override_preserves_other_stages(self):
        result = apply_overrides([self.exam], [{"id":"test-2027","events":{"exam":{"start":"2026-12-06"}}}])
        self.assertIn("registration", result[0]["events"])

    def test_repository_data_passes_validation(self):
        validate(load("sources.json"), apply_overrides(load("exams.json", []), load("overrides.json")))


if __name__ == "__main__":
    unittest.main()
