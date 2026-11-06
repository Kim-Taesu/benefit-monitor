import unittest
from benefit_monitor.collectors.html import ArticleLinks

class RemainingSourceTests(unittest.TestCase):
    def test_reservation_same_service_is_one_candidate_with_stable_title(self):
        p=ArticleLinks('https://yeyak.seoul.go.kr/web/main.do',['yeyak.seoul.go.kr'],r'/web/reservation/selectReservView.do',['체험'])
        p.feed('<a href="/web/reservation/selectReservView.do?rsv_svc_id=S123&amp;reSvc=Y" title="숲 체험">접수중 무료 20명</a><a href="/web/reservation/selectReservView.do?rsv_svc_id=S123&amp;reSvc=N" title="숲 체험">마감 0명</a>')
        self.assertEqual(p.items,{'https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=S123':'숲 체험'})

    def test_seven_card_tabs_are_allowlisted_data_not_executed_javascript(self):
        p=ArticleLinks('https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=2',['www.7-eleven.co.kr'],r'/product/cardInfo.asp',['할인','멤버십'])
        p.feed('<a href="/product/cardInfo.asp">할인·멤버십 카드</a><a href="javascript: fncTab(\'2\');">할인 카드</a><a href="javascript: fncTab(\'3\');">멤버십 카드</a><a href="javascript: fncTab(\'4\');">할인</a><a href="javascript:alert(1)">할인</a>')
        self.assertEqual(p.items,{'https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=2':'할인 카드','https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=3':'멤버십 카드'})
        foreign=ArticleLinks('https://official.example/',['official.example'],r'/product/cardInfo.asp',['할인'])
        foreign.feed('<a href="javascript: fncTab(\'2\');">할인</a>')
        self.assertEqual(foreign.items,{})

    def test_emart24_event_cards_keep_listed_period_after_name(self):
        p=ArticleLinks('https://emart24.co.kr/event/ing',['emart24.co.kr','www.emart24.co.kr'],r'/event/\d+',['이벤트','할인'])
        p.feed('<a href="/event/ing">진행중인 이벤트</a>'
               '<a class="eventWrap" href="/event/8501"><!-- <div class="eTit">진행중</div>--><div class="eventImg"><img src="https://emart24.co.kr/image/x" alt=""/></div>'
               '<p><span>2026-11-01 ~\n 2026-11-10</span><br />\n 11월 빼빼로데이 이벤트\n</p></a>'
               '<a class="eventWrap" href="/event/8500"><p><span>2026-10-16 ~ 2026-11-15</span><br/>플래그십 스토어 개점</p></a>')
        self.assertEqual(p.items,{'https://emart24.co.kr/event/8501':'11월 빼빼로데이 이벤트 (2026-11-01 ~ 2026-11-10)'})

    def test_seven_event_views_become_list_fragments_without_executing_javascript(self):
        route='https://www.7-eleven.co.kr/event/eventList.asp'
        p=ArticleLinks(route,['www.7-eleven.co.kr'],r'/event/eventList.asp',['*'])
        p.feed('<a href="/event/eventList.asp">진행중인 이벤트</a>'
               '<a href="javascript: fncGoView(\'1368\', \'1\');" class="event_img"><img src="/upload/a.png" alt="2026년 11월 호빵" /></a>'
               '<a href="javascript: fncGoView(\'1368\', \'1\');" class="event_img"><img alt="2026년 11월 호빵" /></a>'
               '<a href="javascript: fncEventList();">더보기</a><a href="javascript:alert(1)">할인</a>')
        self.assertEqual(p.items,{route+'#seqNo=1368':'2026년 11월 호빵'})
        foreign=ArticleLinks('https://official.example/event/eventList.asp',['official.example'],r'/event/eventList.asp',['*'])
        foreign.feed('<a href="javascript: fncGoView(\'1\', \'1\');"><img alt="호빵"/></a>')
        self.assertEqual(foreign.items,{})

    def test_event_sources_are_kept_out_of_paid_research(self):
        import json
        from pathlib import Path
        sources={s['id']:s for s in json.loads(Path(__file__).resolve().parents[1].joinpath('sources.yaml').read_text())['sources']}
        self.assertFalse(sources['emart24_events']['ai_review'])
        self.assertFalse(sources['seven_events']['ai_review'])
        self.assertNotIn('ai_review',sources['seoul'])
