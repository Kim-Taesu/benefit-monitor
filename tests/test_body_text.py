import unittest
from benefit_monitor.collectors.body import extract_body


class BodyTextTests(unittest.TestCase):
    def test_unique_main_keeps_all_conditions_and_ignores_outer_navigation(self):
        text,mode=extract_body('<header>사이트 제목</header><nav>바깥 조회 10</nav><main><header>신청 조건</header><article>조회 5회 이상 · 신청 (1건)</article><p>공통 조건 1만원</p></main><footer>하단 링크</footer>')
        self.assertEqual(mode,'main');self.assertEqual(text,'신청 조건 조회 5회 이상 · 신청 (1건) 공통 조건 1만원')

    def test_unique_article_is_only_used_without_main(self):
        self.assertEqual(extract_body('<div>조회 10</div><article>신청 1건</article><div>관련 뉴스</div>'),('신청 1건','article'))

    def test_ambiguous_or_unclosed_regions_fall_back_without_dropping_other_conditions(self):
        for page in ['<main>A</main><main>B</main>','<article>A</article><article>B</article>','<main>A<article>B</article>','<div>A<br>B<img src="not-fetched"><p>C</p></div>']:
            text,mode=extract_body(page);self.assertEqual(mode,'document');self.assertIn('A',text);self.assertIn('B',text)

    def test_scripts_styles_and_footer_do_not_become_conditions(self):
        self.assertEqual(extract_body('<main>A<script>fake</script><style>fake</style><footer>fake</footer><p>B &amp; C</p></main>'),('A B & C','main'))

    def test_metadata_like_words_inside_main_are_not_removed(self):
        text,_=extract_body('<main>조회 5 · 공감수 7 · (1건) 기사 관련 태그 지원금 5,000원</main>')
        self.assertIn('조회 5',text);self.assertIn('(1건)',text);self.assertIn('지원금 5,000원',text)

    def test_deep_markup_is_bounded(self):
        with self.assertRaises(ValueError):extract_body('<div>'*300+'text'+'</div>'*300)


class SeoulBodyScopeTests(unittest.TestCase):
    URL = 'https://mediahub.seoul.go.kr/archives/2019868'

    def test_verified_host_and_article_path_use_unique_official_body_class(self):
        page = '<main>조회 99<div class="extra news_detail_cont"><p>조회 5회 이상 · 지원 1,000원</p><header>신청 (1건)</header></div>다른 추천 기사</main>'
        self.assertEqual(extract_body(page, self.URL), ('조회 5회 이상 · 지원 1,000원 신청 (1건)', 'seoul_news'))

    def test_same_class_on_other_hosts_or_routes_is_not_trusted(self):
        page = '<main>공통 조건<div class="news_detail_cont">일부 조건</div></main>'
        for url in ['https://other.example/archives/1', 'https://mediahub.seoul.go.kr/search', 'https://mediahub.seoul.go.kr/archives/1/extra', None]:
            with self.subTest(url=url):
                self.assertEqual(extract_body(page, url), ('공통 조건 일부 조건', 'main'))

    def test_duplicate_or_unclosed_official_scopes_keep_whole_document(self):
        for page in ['밖 조건<main><div class="news_detail_cont">A</div><div class="news_detail_cont">B</div></main>', '밖 조건<main><div class="news_detail_cont">A</main>']:
            text, mode = extract_body(page, self.URL)
            self.assertEqual(mode, 'document')
            self.assertIn('밖 조건', text)
            self.assertIn('A', text)

    def test_legacy_mode_still_reproduces_v3_hash_input(self):
        page = '<main>조회 99<div class="news_detail_cont">조건 1,000원</div></main>'
        self.assertEqual(extract_body(page), ('조회 99 조건 1,000원', 'main'))


class StableTextTests(unittest.TestCase):
    """2026-11-14: view counters changed the body hash every day and withdrew published items."""

    def test_view_counters_are_dropped_and_the_result_is_stable(self):
        from benefit_monitor.collectors.body import stable_text
        for raw, want in (('등록일 2026-11-05 조회수 475 첨부파일 없음', '등록일 2026-11-05 조회수 첨부파일 없음'),
                          ('작성일 : 2026-10-20 조회 : 1,657 담당부서', '작성일 : 2026-10-20 조회 : 담당부서'),
                          ('조회수475 좋아요 12 공유', '조회수 좋아요 공유'),
                          ('조회수 : 30 목록', '조회수 : 목록'), ('작성자 보건소 조회수 475.', '작성자 보건소 조회수.')):
            self.assertEqual(stable_text(raw), want)
            self.assertEqual(stable_text(want), want)
        self.assertEqual(stable_text('조회수 446 본문'), stable_text('조회수 475 본문'))

    def test_dates_and_counted_conditions_are_kept(self):
        from benefit_monitor.collectors.body import stable_text
        for text in ('조회 2026.11.05 등록', '조회수 2026-11-05', '조회 5회 이상 시 지급', '조회 3건당 100원',
                     '지원금 5,000원 · 정원 30명 · 11월 30일까지', '좋아요 10개 이상 받은 글', '조회수 100회 이상',
                     '환급금 조회 24시간 가능', '조회 3단계 절차', '문의 조회 02 123 4567', '조회 5 · 공감수 7'):
            self.assertEqual(stable_text(text), text)

    def test_reader_hashes_the_stable_body(self):
        import hashlib, io, json, tempfile
        from datetime import datetime
        from pathlib import Path
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        from benefit_monitor import cost_policy
        from benefit_monitor.official_reader import OfficialReader
        root = Path(__file__).resolve().parents[1]
        now = datetime(2026, 11, 14, 7, tzinfo=ZoneInfo('Asia/Seoul'))
        page = '<html><main>치매 선별 검진 안내 등록일 2026-11-05 조회수 %d 첨부파일 없음. 12월 찾아가는 치매 선별검진을 실시합니다. 대상은 만 60세 이상 노원구민이며 비용은 무료입니다. 신분증을 지참하고 가까운 동 주민센터로 방문하면 됩니다.</main></html>'

        class Response(io.BytesIO):
            headers = {'Content-Type': 'text/html; charset=utf-8'}
        hashes = []
        for count in (446, 475):
            with tempfile.TemporaryDirectory(dir=root) as temp:
                (Path(temp)/'sources.yaml').write_text(json.dumps({'sources': [{'id': 'seoul', 'domains': ['www.seoul.go.kr']}]}))
                cost_policy.reset(10)
                body = (page % count).encode()
                with patch('benefit_monitor.official_reader.network_open',
                           side_effect=lambda r: Response(b'User-agent: *\nAllow: /' if r.full_url.endswith('/robots.txt') else body)):
                    doc = OfficialReader(temp, now).read({'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/1'})
            self.assertNotIn(str(count), doc['body'])
            self.assertEqual(doc['body_hash'], hashlib.sha256(doc['body'].encode()).hexdigest())
            hashes.append(doc['body_hash'])
        self.assertEqual(hashes[0], hashes[1])
