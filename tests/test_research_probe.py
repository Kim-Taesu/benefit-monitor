import copy
import json
import socket
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from benefit_monitor.research_probe import run, NoRedirect

class Response:
    headers = {'Content-Type':'text/html; charset=utf-8'}
    def __init__(self, text): self.body = text.encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.body[:limit]

class Opener:
    def __init__(self, replies): self.replies=iter(replies); self.urls=[]
    def open(self, request, timeout):
        self.urls.append(request.full_url)
        result=next(self.replies)
        if isinstance(result, Exception): raise result
        return Response(result)

class ResearchProbeTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((Path(__file__).resolve().parents[1]/'sources.yaml').read_text())
        self.now=datetime(2026,11,4,15,tzinfo=timezone.utc)
        self.seed='<html><a href="/archives/123">모집 공고</a></html>'

    def test_realistic_success_sequence(self):
        opener=Opener(['User-agent: *\nAllow: /',self.seed,'<html>공식 공고</html>'])
        report=run(self.config,now=self.now,opener=opener)
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['documents_read'],2)
        self.assertEqual(report['request_attempts'],3)
        self.assertTrue(opener.urls[0].endswith('/robots.txt'))

    def test_dns_stops_without_retry(self):
        opener=Opener([URLError(socket.gaierror(8,'unavailable'))])
        report=run(self.config,now=self.now,opener=opener)
        self.assertEqual(report['failure_stage'],'dns')
        self.assertEqual(report['documents_read'],0)
        self.assertEqual(len(opener.urls),1)

    def test_robots_denial_does_not_fetch_body(self):
        opener=Opener(['User-agent: *\nDisallow: /'])
        report=run(self.config,now=self.now,opener=opener)
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(len(opener.urls),1)

    def test_link_robots_checked(self):
        opener=Opener(['User-agent: *\nDisallow: /archives/', self.seed])
        report=run(self.config,now=self.now,opener=opener)
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(len(opener.urls),2)

    def test_cooldown(self):
        previous={'status':'blocked','checked_at':self.now.isoformat()}
        opener=Opener([])
        report=run(self.config,previous,self.now,opener)
        self.assertEqual(report['status'],'cooldown')
        self.assertEqual(opener.urls,[])

    def test_budget_limits_robot_and_body(self):
        config=copy.deepcopy(self.config);config['max_http_requests']=1
        opener=Opener(['User-agent: *\nAllow: /'])
        report=run(config,now=self.now,opener=opener)
        self.assertEqual(report['status'],'blocked')
        self.assertEqual(report['request_attempts'],1)

    def test_404_robots_can_continue(self):
        from io import BytesIO
        stream = BytesIO(b'missing')
        opener=Opener([HTTPError('https://mediahub.seoul.go.kr/robots.txt',404,'missing',{},stream),self.seed,'<html>공고</html>'])
        self.assertEqual(run(self.config,now=self.now,opener=opener)['status'],'passed')
        self.assertTrue(stream.closed)

    def test_redirect_rejected(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None,None,302,'',{},'https://other.example/')

    def test_redirect_destination_recorded_without_following(self):
        for destination in ('https://mediahub.seoul.go.kr/main.do',
                            'https://outside.example/'):
            with self.subTest(destination=destination):
                try:
                    NoRedirect().redirect_request(None,None,302,'',{},destination)
                except ValueError as error:
                    blocked = error
                opener = Opener(['User-agent: *\nAllow: /', blocked])
                report = run(self.config, now=self.now, opener=opener)
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(report['events'][-1].get('redirect_target'), destination)
                self.assertEqual(report['events'][-1].get('http_status'), 302)
                self.assertEqual(report['responses'], 2)
                self.assertEqual(report['request_attempts'], 2)
                self.assertEqual(report['redirects_followed'], 0)
                self.assertEqual(report['documents_read'], 0)
                self.assertEqual(len(opener.urls), 2)

    def test_no_link_is_not_pass(self):
        report=run(self.config,now=self.now,opener=Opener(['','<html>empty</html>']))
        self.assertEqual(report['status'],'blocked')

    def test_crawl_delay_between_real_request_boundaries(self):
        policies = [
            ('User-agent: *\nCrawl-delay: 10\nAllow: /', [0, 10, 20], 'passed'),
            ('User-agent: *\nCrawl-delay: 3600\nAllow: /', [0], 'blocked'),
            ('User-agent: *\nCrawl-delay: 10\nAllow: /\n'
             'User-agent: BenefitMonitor\nAllow: /', [0, 0, 0], 'passed'),
            ('User-agent: BenefitMonitor\nCrawl-delay: 2\nAllow: /\n'
             'User-agent: BenefitMonitor\nCrawl-delay: 5\nAllow: /', [0, 5, 10], 'passed'),
            ('User-agent: *\nCrawl-delay: invalid\nAllow: /', [0], 'blocked'),
        ]
        for policy, expected_times, expected_status in policies:
            with self.subTest(policy=policy):
                elapsed, request_times = [0], []
                class TimedOpener(Opener):
                    def open(self, request, timeout):
                        request_times.append(elapsed[0])
                        return super().open(request, timeout)
                def advance(seconds):
                    elapsed[0] += seconds
                opener = TimedOpener([policy, self.seed, '<html>공고</html>'])
                with patch('time.monotonic', side_effect=lambda: elapsed[0]), \
                     patch('time.sleep', side_effect=advance):
                    report = run(self.config, now=self.now, opener=opener)
                self.assertEqual(report['status'], expected_status)
                self.assertEqual(request_times, expected_times)
