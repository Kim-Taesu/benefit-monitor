import unittest
from datetime import datetime
from unittest.mock import patch

from benefit_monitor import cost_policy
from benefit_monitor.collectors import public

NOW = datetime.fromisoformat('2026-11-04T01:00:00+09:00')
SH = dict(id='sh', domains=['www.i-sh.co.kr'], collector='sh_notice', boards=['rent'])
ESHARE = dict(id='eshare', domains=['www.eshare.go.kr'], collector='eshare',
              queries=[dict(keyword='체험', ctrd='11', free=True, reservable=True)])
HERITAGE = dict(id='heritage', domains=['www.khs.go.kr', 'royal.khs.go.kr'], collector='heritage_events',
                regions=['서울'], include_next_month=True)

SH_LIST = '''<div id="listTb" class="listTable colRm"><table><tbody>
<tr><td>95</td><td class="txtL"><a href="#" onclick="javascript:getDetailView('304371');return false;"><span class="icoNew">NEW</span> 행복주택 예비자 계약결과 알림</a></td><td>공공주택공급부</td><td class="num">2026-05-14</td><td class="num">872</td></tr>
<tr><td>94</td><td class="txtL"><a href="#" onclick="javascript:getDetailView('304380');return false;">2026년 청년 매입임대주택 입주자 모집공고</a></td><td>매입임대부</td><td class="num">2026-11-03</td><td class="num">1,210</td></tr>
</tbody></table></div>'''

ESHARE_FRAGMENT = '''<div class="tabWrap"><p class="num">총 <span>1</span>건</p><ul class="srchList imgList v2">
<li>
  <!--  이미지영역 [s]  --><p class="thumbImg"><img src="/x" alt="x" /></p>
  <div class="info"><strong><a class="sbj_txt" href="#none" onclick="fnNewPageResourceDetail('CPS001.007', 'AB12'); " title="서울 목공 <!HS>체험<!HE> 새창열림">서울 목공 <span class='s_keyword'>체험</span></a></strong>
  <ul class="infoList"><li><strong>자원 분류</strong><span class="c1">교육·체험</span></li>
  <li><strong>위치 정보</strong><span class="c1">서울 은평구 연서로 1</span></li>
  <li><strong>이용 요금</strong><span>무료</span></li></ul>
  <a href="#none" class="btn green" onclick="fnNewPageResourceDetail('CPS001.007','AB12');"><i class="pc_txt"><span class="sr-only">서울 목공 체험</span>예약·문의하기</i></a></div>
</li></ul></div>'''

HERITAGE_XML = '''<?xml version="1.0" encoding="UTF-8"?><result>
<item><subTitle><![CDATA[궁중문화축전 야간 관람]]></subTitle><subPath>https://royal.khs.go.kr/event/1</subPath><sido>서울특별시</sido><gugun>종로구</gugun><sDate>20261101</sDate><eDate>20261130</eDate></item>
<item><subTitle>부산 행사</subTitle><subPath>https://royal.khs.go.kr/event/2</subPath><sido>부산광역시</sido><gugun>중구</gugun></item>
<item><subTitle>외부 링크 행사</subTitle><subPath>https://example.com/e</subPath><sido>서울특별시</sido><gugun>중구</gugun></item>
</result>'''.encode()

ALLOW = b'User-agent: *\nAllow: /'


class PublicCollectorTests(unittest.TestCase):
    def setUp(self):
        cost_policy.reset(60)

    def test_sh_keeps_open_looking_notices_only(self):
        def response(url, domains):
            return ALLOW if url.endswith('/robots.txt') else SH_LIST.encode()
        with patch('benefit_monitor.collectors.public.fetch', side_effect=response):
            items = public.collect(SH, NOW)
        self.assertEqual([i['url'] for i in items], [
            'https://www.i-sh.co.kr/app/lay2/program/S1T294C297/www/brd/m_247/view.do?multi_itm_seq=2&seq=304380'])
        self.assertTrue(items[0]['needs_recheck'])
        self.assertIn('[SH 주택임대] 2026년 청년 매입임대주택 입주자 모집공고', items[0]['title'])

    def test_sh_unexpected_markup_fails_closed(self):
        with patch('benefit_monitor.collectors.public.fetch', side_effect=[ALLOW, b'<html>maintenance</html>']):
            with self.assertRaises(ValueError):
                public.collect(SH, NOW)

    def test_robots_denial_blocks_collection(self):
        with patch('benefit_monitor.collectors.public.fetch', return_value=b'User-agent: *\nDisallow: /'):
            with self.assertRaises(ValueError):
                public.collect(SH, NOW)

    def test_eshare_parses_title_place_and_detail_url(self):
        rows = public.parse_eshare(ESHARE_FRAGMENT)
        self.assertEqual(rows[0]['title'], '서울 목공 체험')
        self.assertEqual(rows[0]['place'], '서울 은평구 연서로 1')
        self.assertEqual(public.eshare_detail_url(rows[0]['rsrc_dcd'], rows[0]['rsrc_no']),
                         'https://www.eshare.go.kr/UserPortal/Upv/UprResrcExpr/index.do?rsrc_no=AB12&rsrc_dcd=CPS001.007')
        self.assertIsNone(public.eshare_detail_url('CPS001.555', 'X'))

    def test_eshare_collect_posts_search_after_bootstrap(self):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return self.body
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append((request.full_url, request.data))
                return Response(ESHARE_FRAGMENT.encode() if request.data else b'<html></html>')
        with patch('benefit_monitor.collectors.public.fetch', return_value=ALLOW), \
                patch('benefit_monitor.collectors.public.urllib.request.build_opener', return_value=Opener()):
            items = public.collect(ESHARE, NOW)
        self.assertEqual(calls[0][0], public.ESHARE_BOOTSTRAP)
        self.assertIn(b'free_yn=Y', calls[1][1])
        self.assertEqual(items[0]['title'], '[공유누리] 서울 목공 체험 · 서울 은평구 연서로 1')
        self.assertEqual(cost_policy.budget.used, 2)  # bootstrap + search; robots is mocked

    def test_heritage_filters_region_official_links_and_dedupes_months(self):
        def response(url, domains):
            return ALLOW if url.endswith('/robots.txt') else HERITAGE_XML
        with patch('benefit_monitor.collectors.public.fetch', side_effect=response) as fetch:
            items = public.collect(HERITAGE, NOW)
        self.assertEqual([i['url'] for i in items], ['https://royal.khs.go.kr/event/1'])
        self.assertTrue(any('searchMonth=12' in c.args[0] for c in fetch.call_args_list))

    def test_unknown_collector_rejected(self):
        with self.assertRaises(ValueError):
            public.collect(dict(SH, collector='paid_api'), NOW)


if __name__ == '__main__':
    unittest.main()
