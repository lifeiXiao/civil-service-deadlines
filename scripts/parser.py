"""Conservative Chinese notice extraction. Never guess an unspecified clock time."""
import re
import unicodedata
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urldefrag


class Page(HTMLParser):
    def __init__(self, html, url):
        super().__init__(convert_charrefs=True)
        self.url, self.parts, self.links = url, [], []
        self.skip, self.anchor, self.title, self.in_title = 0, None, "", False
        self.feed(html)
        self.text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.parts))
        self.text = re.sub(r"\n\s*\n+", "\n", self.text).strip()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if self.skip:
            return
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "td"):
            self.parts.append("\n")
        if tag == "title":
            self.in_title = True
        if tag == "a":
            self.anchor = {"url": urljoin(self.url, attrs.get("href", "")), "text": attrs.get("title", "")}

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "a" and self.anchor:
            self.anchor["text"] = re.sub(r"\s+", "", self.anchor["text"])
            self.links.append(self.anchor)
            self.anchor = None
        if tag == "title":
            self.in_title = False
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        self.parts.append(data)
        if self.anchor:
            self.anchor["text"] += data
        if self.in_title:
            self.title += data


def trusted_url(url, domains):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme in ("http", "https") and not parsed.username and not parsed.password
            and parsed.port in (None, 80, 443)
            and any(host == domain or host.endswith("." + domain) for domain in domains))


def canonical(url):
    return urldefrag(url)[0]


def notice_year(title):
    match = re.search(r"(20\d{2})\s*年", title)
    return int(match[1]) if match else None


def is_notice(title, source, years):
    compact = re.sub(r"\s+", "", title)
    if notice_year(compact) not in years or "公务员" not in compact:
        return False
    if re.search(r"遴选|选调|拟录用|公示名单|体检|考察|面试|录用人员|事业单位|专业能力测试|调剂|补充录用", compact):
        return False
    if source["id"] != "national" and re.search(r"中央机关|国家公务员|国考", compact):
        return False
    if source["id"] == "national" and not re.search(r"中央机关|国家公务员|国考", compact):
        return False
    return bool(re.search(r"公告|报名|准考证|笔试|缴费|时间|安排|通知|专题|成绩", compact))


# A second date may omit year/month, e.g. 2026年11月2日9:00至6日16:00.
DATE = re.compile(r"(?:(?P<y>20\d{2})年)?(?:(?P<m>\d{1,2})月)?(?P<d>\d{1,2})日"
                  r"(?:[（(][^）)\n]{1,8}[）)])?\s*(?P<period>上午|下午|晚上)?\s*"
                  r"(?:(?P<h>\d{1,2})(?:[:：︰](?P<minute>\d{1,2})|[时点](?P<cnminute>\d{1,2})?分?))?")
KEYS = {
    "registration": r"报名时间|注册报名|提交报考申请|提交报名申请|报名和提交报考申请时间|网上报名时间|进行报名|进行网上报名",
    "payment": r"缴费时间|缴费确认|确认缴费|报名确认并缴费|网上确认及缴费|确认和缴费|进行网上缴费",
    "admission": r"打印.{0,8}准考证|准考证.{0,8}打印|下载.{0,6}准考证",
    "exam": r"公共科目笔试时间|公共科目笔试将于|公共科目笔试|笔试时间为|笔试时间[:：\n]",
}


def date_tokens(text):
    text = unicodedata.normalize("NFKC", text.replace("︰", ":").replace("∶", ":"))
    result, year, month = [], None, None
    for match in DATE.finditer(text):
        year = int(match["y"]) if match["y"] else year
        month = int(match["m"]) if match["m"] else month
        if year is None or month is None:
            continue
        day = int(match["d"])
        try:
            value = datetime(year, month, day)
            precision = "date"
            if match["h"] is not None:
                hour = int(match["h"])
                minute = int(match["minute"] or match["cnminute"] or 0)
                if match["period"] in ("下午", "晚上") and hour < 12:
                    hour += 12
                if hour == 24 and minute == 0:
                    value += timedelta(days=1)
                    hour = 0
                value = value.replace(hour=hour, minute=minute)
                precision = "minute"
            iso = value.strftime("%Y-%m-%dT%H:%M:00+08:00") if precision == "minute" else value.strftime("%Y-%m-%d")
            result.append({"value": iso, "precision": precision, "offset": match.start(), "end_offset": match.end()})
        except ValueError:
            continue
    return result


def extract_events(text, url):
    text = unicodedata.normalize("NFKC", text.replace("︰", ":").replace("∶", ":"))
    events = {}
    for key, pattern in KEYS.items():
        candidates = []
        for marker in re.finditer(pattern, text):
            # Find dates in the same sentence/short following paragraph only.
            start = max(text.rfind(separator, 0, marker.start()) for separator in ("。", "\n", ";", "；")) + 1
            stops = [text.find(separator, marker.end()) for separator in ("。", ";", "；")]
            stop = min([position for position in stops if position != -1] + [len(text), marker.end() + 170])
            window = text[start:stop]
            if re.search(r"取消|延期|另行通知|待定", window):
                continue
            if key == "registration" and re.search(r"调剂|职位报名|改报|补报|补充录用", window):
                continue
            if key == "admission" and not re.search(r"时间|请于|可于|应于|自|从|至", window):
                continue
            if key == "payment" and (re.search(r"缴费确认后|缴费成功后|准考证", window)):
                continue
            tokens = date_tokens(window)
            if not tokens:
                continue
            # Reject ambiguous sentences mentioning multiple types of date windows.
            if key != "exam" and len(tokens) > 2:
                continue
            if key == "exam":
                tokens = tokens[:1]
            first, last = tokens[0], tokens[-1] if len(tokens) > 1 else None
            if key in ("registration", "payment") and last is None:
                continue
            if last and first["value"] > last["value"]:
                continue
            if last and (datetime.fromisoformat(last["value"][:10]) - datetime.fromisoformat(first["value"][:10])).days > 90:
                continue
            candidates.append({"start": first["value"], "end": last["value"] if last else None,
                               "source_url": url, "evidence": window.strip()[:220], "verification": "auto"})
        unique = {(c["start"], c["end"]): c for c in candidates}
        if len(unique) == 1:
            events[key] = next(iter(unique.values()))
    return events
