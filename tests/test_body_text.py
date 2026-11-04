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
