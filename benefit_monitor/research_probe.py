"""Bounded, read-only official HTTPS probe; no API, publication or redirects.

Run with python3 -m benefit_monitor.research_probe. Runtime state is separate
from production collection caches. District endpoints are not fetched.
"""
import argparse
import hashlib
import json
import socket
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .collectors.html import ArticleLinks
from .collectors.rss import AGENT, LIMIT
from .cost_policy import RequestBudget, require_free
from .robots import allowed
from .validation import official


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect_not_followed: destination needs separate policy review')


def error_stage(error):
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return 'dns'
    if isinstance(reason, ssl.SSLError):
        return 'tls'
    if isinstance(error, HTTPError):
        return 'http'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'timeout'
    return 'transport_or_policy'


def run(config, previous=None, now=None, opener=None):
    """Return audit report; never stores body content or performs retries."""
    require_free(config)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must include timezone')
    budget = RequestBudget(min(config.get('max_http_requests', 60), 6))
    report = {'schema_version':'research-probe-v1', 'checked_at':now.isoformat(),
              'status':'blocked', 'request_limit':budget.limit, 'request_attempts':0,
              'responses':0, 'documents_read':0, 'events':[], 'external_llm_calls':0,
              'redirects_followed':0, 'retry_count':0, 'mode':'read_only_research'}
    if previous and previous.get('status') != 'passed':
        elapsed = (now-datetime.fromisoformat(previous['checked_at'])).total_seconds()
        if elapsed < 900:
            report.update(status='cooldown', reason='15-minute failure cooldown',
                          checked_at=previous['checked_at'])
            return report
    source = next(s for s in config['sources'] if s['id'] == 'seoul')
    route = source['html_url']
    robot_url = 'https://' + urlsplit(route).netloc + '/robots.txt'
    opener = opener or build_opener(NoRedirect())  # default TLS verification and inherited proxy
    robots = {}

    def fetch(url, role):
        if not official(url, source['domains']):
            raise ValueError('URL outside official HTTPS allowlist')
        if role != 'robots' and not allowed(robots[urlsplit(url).netloc], url, AGENT):
            raise ValueError('robots disallows URL')
        budget.consume()
        event = {'url':url, 'role':role, 'status':'attempted'}
        report['events'].append(event)
        try:
            with opener.open(Request(url, headers={'User-Agent':AGENT}), timeout=15) as response:
                report['responses'] += 1
                body = response.read(LIMIT+1)
                if len(body) > LIMIT:
                    raise ValueError('response exceeds 2 MiB')
                text = body.decode('utf-8', 'strict')
                if role != 'robots':
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'text/html' not in content_type:
                        raise ValueError('unsupported content type')
                    if not text.strip() or not any(t in text.lower() for t in ('<html', '<!doctype', '<article', '<main')):
                        raise ValueError('empty or non-HTML document')
                    report['documents_read'] += 1
                event.update(status='ok', bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                return text
        except HTTPError as error:
            report['responses'] += 1
            if role == 'robots' and error.code == 404:
                event.update(status='missing_robots_404')
                return ''
            event.update(status='failed', stage=error_stage(error), error=str(error))
            raise
        except Exception as error:
            event.update(status='failed', stage=error_stage(error), error=str(error))
            raise

    try:
        robots[urlsplit(route).netloc] = fetch(robot_url, 'robots')
        body = fetch(route, 'seed')
        parser = ArticleLinks(route, source['domains'], source['article_path_pattern'], source['keywords'])
        parser.feed(body)
        links = [u for u in parser.items if u != route]
        if not links:
            raise ValueError('no eligible linked article in seed; no success claim')
        target = links[0]
        host = urlsplit(target).netloc
        if host not in robots:
            robots[host] = fetch('https://' + host + '/robots.txt', 'robots')
        fetch(target, 'linked_article')
        report.update(status='passed', reason='seed and linked article read under robots policy')
    except Exception as error:
        report.update(reason=str(error), failure_stage=error_stage(error))
    report['request_attempts'] = budget.used
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    output = root / '.tools/phase01/network-probe.json'
    previous = json.loads(output.read_text()) if output.exists() else None
    result = run(json.loads((root/'sources.yaml').read_text()), previous)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
