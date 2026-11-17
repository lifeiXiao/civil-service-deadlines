"""Check official public notice pages; retain old data when a source fails.

Runs in GitHub Actions. Standard library only; no tokens, local service, LLM,
or paid search API are used. Collection is bounded and respects robots.txt.
"""
import argparse
import hashlib
import json
import re
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlsplit

from scripts.common import CST, ROOT, cycle_year, load, now_iso, save
from scripts.parser import Page, canonical, extract_events, is_notice, notice_year, trusted_url

AGENT = "CivilServiceCalendar/1.0 (+https://github.com/lifeiXiao/civil-service-deadlines)"
MAX_BYTES = 3 * 1024 * 1024


class Fetcher:
    def __init__(self, domains, timeout=12):
        self.domains, self.timeout = domains, timeout
        self.robots, self.last_request = {}, {}

    def raw(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"})
        # Bound redirects and revalidate every redirect target before sending.
        domains = self.domains

        class SafeRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if not trusted_url(newurl, domains):
                    raise ValueError("拒绝跳转到未配置的域名")
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(SafeRedirect)
        with opener.open(request, timeout=self.timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type and not any(kind in content_type for kind in ("text/", "application/xhtml", "application/xml")):
                raise ValueError("不是可解析的公开文本网页")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("网页超过大小限制")
            declared = response.headers.get_content_charset()
            if not declared:
                meta = re.search(br'charset\s*=\s*["\x27]?([\w-]+)', raw[:10000], re.I)
                declared = meta[1].decode("ascii", errors="ignore") if meta else None
            for encoding in dict.fromkeys([declared, "utf-8", "gb18030"]):
                if not encoding:
                    continue
                try:
                    return raw.decode(encoding), response.geturl()
                except (UnicodeDecodeError, LookupError):
                    continue
            raise ValueError("无法识别网页编码")

    def page(self, url):
        if not trusted_url(url, self.domains):
            raise ValueError("未配置的官网域名")
        split = urlsplit(url)
        origin = f"{split.scheme}://{split.netloc}"
        if origin not in self.robots:
            rules = urllib.robotparser.RobotFileParser()
            try:
                text, _ = self.raw(origin + "/robots.txt")
                rules.parse(text.splitlines())
            except urllib.error.HTTPError as exc:
                rules.parse(["User-agent: *", "Disallow: /"] if exc.code in (401, 403) else [])
            except (OSError, ValueError):
                # An unavailable robots endpoint is distinct from an explicit ban.
                rules.parse([])
            self.robots[origin] = rules
        rules = self.robots[origin]
        if not rules.can_fetch(AGENT, url):
            raise PermissionError("官网 robots.txt 不允许自动读取")
        pause = max(0.6, rules.crawl_delay(AGENT) or rules.crawl_delay("*") or 0)
        if pause > 10:
            raise PermissionError("官网要求较长抓取间隔，暂不自动读取")
        time.sleep(max(0, pause - (time.monotonic() - self.last_request.get(origin, 0))))
        self.last_request[origin] = time.monotonic()
        html, actual_url = self.raw(url)
        page = Page(html, actual_url)
        if len(page.text) < 100 or re.search(r"Access Denied|Just a moment|安全验证|人机验证|访问过于频繁|404.{0,15}Not Found", page.title, re.I):
            raise PermissionError("官网返回验证页面或不可用页面")
        return page


def inspect_source(source, years, timeout):
    fetcher = Fetcher(source["domains"], timeout)
    status = {"id": source["id"], "checked_at": now_iso(), "state": "error", "errors": [], "pages_checked": 0}
    notices, seen, queue, sections = [], set(), [], []
    for url in source.get("seeds", []):
        queue.append((url, "", True))
    for template in source["urls"]:
        queue.append((template.format(year=max(years)), "", False))
    # Main pages -> at most two relevant list pages -> at most six notices.
    for url, known_title, is_article in queue:
        url = canonical(url)
        if url in seen or len(seen) >= 12:
            continue
        seen.add(url)
        try:
            page = fetcher.page(url)
            status["pages_checked"] += 1
            title = known_title or page.title.strip()
            if is_article and is_notice(title, source, years):
                events = extract_events(page.text, url)
                correction = bool(re.search(r"延期|更正|调整|变更|取消|上半年|下半年|第[一二三123]批", title))
                # City or agency-specific notices are visible but cannot define a province's timetable.
                scope_ok = bool(re.search(r"中央机关及其直属机构", title)) if source["id"] == "national" else source["name"] in title
                notices.append({"region_id": source["id"], "year": notice_year(title), "title": title[:160],
                                "url": url, "content_hash": hashlib.sha256(page.text.encode()).hexdigest(),
                                "events": events, "review": correction or not scope_ok or not events})
            elif is_article:
                # Seed pages can have generic titles; verified manual data stays intact.
                pass
            else:
                candidates = [link for link in page.links if trusted_url(link["url"], source["domains"])
                              and is_notice(link["text"], source, years)
                              and not re.search(r"\.(pdf|docx?|xlsx?)(?:\?|$)", link["url"], re.I)]
                for link in candidates[:6]:
                    queue.append((link["url"], link["text"], True))
                if not candidates and len(sections) < 2:
                    for link in page.links:
                        if (trusted_url(link["url"], source["domains"]) and link["url"] not in seen
                                and re.search(r"公务员.{0,8}(考试|招录|考录|录用)|招考公告|招录公告", link["text"])
                                and len(link["text"]) < 35 and len(sections) < 2):
                            sections.append(link["url"])
                            queue.append((link["url"], "", False))
        except (OSError, ValueError, PermissionError, urllib.error.URLError, socket.timeout) as exc:
            status["errors"].append({"url": url, "message": str(exc)[:200]})
    status["state"] = "ok" if notices else ("limited" if status["pages_checked"] else "error")
    status["notices_found"] = len(notices)
    return status, notices


def merge_notices(exams, notices, found, checked_at):
    """Never silently overwrite a known deadline with a conflicting candidate."""
    records = {exam["id"]: exam for exam in exams}
    by_url = {notice["url"]: notice for notice in notices}
    for incoming in found:
        url = incoming["url"]
        previous = by_url.get(url, {})
        item = {**previous, **incoming, "first_seen_at": previous.get("first_seen_at", checked_at), "last_seen_at": checked_at}
        if previous.get("content_hash") and previous["content_hash"] != incoming["content_hash"]:
            item["changed_at"] = checked_at
        exam_id = f'{incoming["region_id"]}-{incoming["year"]}'
        record = records.get(exam_id)
        if record is None and incoming["events"] and not incoming["review"]:
            record = {"id": exam_id, "region_id": incoming["region_id"], "year": incoming["year"],
                      "announcement_url": url, "events": {}, "notes": [], "updated_at": checked_at}
            records[exam_id] = record
        item["conflicts"] = []
        if record and not incoming["review"]:
            for key, event in incoming["events"].items():
                old = record["events"].get(key)
                if old and (old["start"], old.get("end")) != (event["start"], event.get("end")):
                    item["conflicts"].append({"stage": key, "existing": old, "candidate": event})
                    item["review"] = True
                elif not old:
                    record["events"][key] = event
                    record["updated_at"] = checked_at
        by_url[url] = item
    return sorted(records.values(), key=lambda record: record["id"]), sorted(by_url.values(), key=lambda item: item.get("first_seen_at", ""), reverse=True)[:500]


def apply_overrides(exams, overrides):
    records = {exam["id"]: exam for exam in exams}
    for override in overrides:
        previous = records.get(override["id"], {})
        records[override["id"]] = {**previous, **override, "events": {**previous.get("events", {}), **override.get("events", {})}}
    return list(records.values())


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--only", help="Comma-separated source IDs for a diagnostic run")
    args.add_argument("--workers", type=int, default=4)
    args.add_argument("--timeout", type=int, default=12)
    options = args.parse_args()
    sources = load("sources.json", [])
    if options.only:
        selected = set(options.only.split(","))
        sources = [source for source in sources if source["id"] in selected]
        if len(sources) != len(selected):
            raise SystemExit("Unknown source ID")
    attempted_at = now_iso()
    exams = apply_overrides(load("exams.json", []), load("overrides.json", []))
    notices = load("notices.json", [])
    previous_status = load("status.json", {})
    status_map = {item["id"]: item for item in previous_status.get("sources", [])}
    found = []
    year = cycle_year()
    with ThreadPoolExecutor(max_workers=max(1, min(options.workers, 6))) as pool:
        tasks = {pool.submit(inspect_source, source, {year - 1, year}, options.timeout): source for source in sources}
        for task in as_completed(tasks):
            source = tasks[task]
            try:
                status, discoveries = task.result()
            except Exception as exc:
                status, discoveries = {"id": source["id"], "checked_at": now_iso(), "state": "error", "errors": [{"message": str(exc)[:200]}], "pages_checked": 0, "notices_found": 0}, []
            status["last_success_at"] = status["checked_at"] if status["state"] == "ok" else status_map.get(source["id"], {}).get("last_success_at")
            status_map[source["id"]] = status
            found.extend(discoveries)
            print(f'{source["name"]}: {status["state"]}, pages={status["pages_checked"]}, notices={len(discoveries)}', flush=True)
    exams, notices = merge_notices(exams, notices, found, attempted_at)
    save("exams.json", exams)
    save("notices.json", notices)
    statuses = sorted(status_map.values(), key=lambda item: item["id"])
    current = [status_map[source["id"]] for source in sources]
    successes = sum(item["state"] == "ok" for item in current)
    report = {"last_attempt_at": attempted_at, "finished_at": now_iso(), "cycle_year": year,
              "last_full_check_at": now_iso() if len(sources) == 32 else previous_status.get("last_full_check_at"),
              "schedule": "每天北京时间 07:23（GitHub 调度可能延迟）", "sources": statuses,
              "summary": {"checked": len(current), "readable": sum(item.get("pages_checked", 0) > 0 for item in current), "with_notices": successes}}
    save("status.json", report)
    summary_file = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(f"## 官网检查\n\n检查 {len(current)} 个地区，{successes} 个地区找到可解析公告。\n\n")
            for item in current:
                handle.write(f'- {item["id"]}: {item["state"]}, pages={item.get("pages_checked", 0)}\n')
    # Still save diagnostic state if every source is unavailable; fail visibly in Actions.
    if not any(item.get("pages_checked", 0) for item in current):
        raise SystemExit("所有来源读取失败：保留旧日期，检查官网网络或来源配置。")


if __name__ == "__main__":
    main()
