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
