import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from ..validation import official
from ..robots import allowed
from .. import cost_policy

AGENT = "BenefitMonitor/0.1"
LIMIT = 2*1024*1024

class Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, domains):
        self.domains = domains
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not official(newurl, self.domains):
            raise ValueError("Redirect outside official hosts")
        cost_policy.budget.consume()
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch(url, domains):
    if not official(url, domains):
        raise ValueError("Unapproved URL")
    opener = urllib.request.build_opener(Redirect(domains))
    for attempt in range(2):
        try:
            cost_policy.budget.consume()
            with opener.open(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=15) as r:
                body = r.read(LIMIT+1)
                if len(body) > LIMIT:
                    raise ValueError("Response too large")
                return body
        except urllib.error.HTTPError as e:
            if e.code not in (502, 503, 504) or attempt:
                raise
        except TimeoutError:
            if attempt:
                raise
        time.sleep(1)

def parse(body, source):
    root = ET.fromstring(body)
    result = []
    usable = 0
    for entry in root.findall(".//item") + root.findall("{http://www.w3.org/2005/Atom}entry"):
        title = entry.findtext("title") or entry.findtext("{http://www.w3.org/2005/Atom}title") or ""
        url = entry.findtext("link")
        if not url:
            link = entry.find("{http://www.w3.org/2005/Atom}link")
            url = link.get("href") if link is not None else None
        if title.strip() and url and official(url, source["domains"]):
            usable += 1
            if source.get("keywords") and not any(word in title for word in source["keywords"]):
                continue
            result.append(dict(source=source["id"], url=url, title=title.strip(),
                               summary="공식 피드 후보. 상세 조건 검증 필요.", needs_recheck=True))
    if not usable:
        raise ValueError("No usable entries; browser review required")
    return result

def collect(source):
    url = source["feed_url"]
    u = urlsplit(url)
    robots = fetch(f"{u.scheme}://{u.netloc}/robots.txt", source["domains"]).decode("utf-8")
    if not allowed(robots, url, AGENT):
        raise ValueError("robots disallows feed")
    return parse(fetch(url, source["domains"]), source)

