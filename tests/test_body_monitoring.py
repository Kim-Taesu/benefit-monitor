import unittest
from datetime import timedelta
from unittest.mock import patch
from benefit_monitor import operations, cost_policy
from test_pipeline import benefit, SOURCE, NOW


class BodyMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.item=benefit();cost_policy.reset(60)
        self.padding='공식 조건은 이용 전 확인해야 하며 개인 자격과 재고는 별도입니다. '*5

    def check(self,state,page,now=NOW):
        calls=[]
        def response(url,domains):
            cost_policy.budget.consume();calls.append(url)
            return b'User-agent: *\nAllow: /' if url.endswith('/robots.txt') else page.encode()
        with patch('benefit_monitor.collectors.rss.fetch',side_effect=response):
            errors=operations.check_bodies(state,[self.item],{'test':SOURCE},now,1)
        return errors,calls

    def test_condition_counts_and_metadata_like_words_are_not_erased(self):
        for old,new in [('조회 5회 이상 신청 (1건)','조회 10회 이상 신청 (2건)'),('기사 관련 태그 프로그램 지원 1,000원','기사 관련 태그 프로그램 지원 2,000원')]:
            with self.subTest(condition=old):
                state={};self.check(state,'<main>'+self.padding+old+'</main>')
                self.check(state,'<main>'+self.padding+new+'</main>',NOW+timedelta(hours=1))
                row=state['items'][self.item.id];self.assertEqual(row['hold_reason'],'body_changed');self.assertEqual(row['body_comparison'],'changed')
                held=operations.observe(state,[],[self.item],NOW+timedelta(hours=1))[0]
                self.assertTrue(held.needs_recheck);self.assertEqual(held.verified_at,self.item.verified_at)

    def test_outer_noise_does_not_hide_or_rewrite_main_conditions(self):
        state={};body='<main>'+self.padding+'비용 1,000원</main>'
        self.check(state,'<div>조회 10</div>'+body+'<section>다른 뉴스 A</section>')
        self.check(state,'<div>조회 99</div>'+body+'<section>다른 뉴스 B</section>',NOW+timedelta(hours=1))
        row=state['items'][self.item.id];self.assertNotIn('hold_reason',row);self.assertEqual(row['body_comparison'],'same');self.assertEqual(row['body_parse_mode'],'main')

    def test_v2_migration_still_checks_the_known_legacy_comparison(self):
        for changed in [False,True]:
            with self.subTest(changed=changed):
                text=self.padding+'비용 1,000원'
                row=dict(source='test',body_hash=operations.digest(operations.article_text(text)),body_hash_version=2,body_target_hash=operations.digest(self.item.url))
                state={'items':{self.item.id:row}}
                self.check(state,'<main>'+text.replace('1,000','2,000' if changed else '1,000')+'</main>')
                self.assertEqual(row['body_hash_version'],operations.BODY_HASH_VERSION)
                self.assertEqual(row['body_comparison'],'changed' if changed else 'baseline')
                self.assertEqual(row.get('hold_reason'),'body_changed' if changed else None)

    def test_scope_metadata_is_projected_without_raw_source_or_url(self):
        state={};self.check(state,'<article>'+self.padding+'확인 조건</article>')
        row=state['items'][self.item.id];self.assertEqual(row['body_comparison'],'baseline');self.assertEqual(row['body_parse_mode'],'article')
        row['body_html']='private-looking content'
        clean=operations.sanitize(state|{'schema_version':1},{'test'},NOW)
        saved=clean['items'][self.item.id];self.assertEqual(saved['body_parse_mode'],'article');self.assertEqual(saved['body_comparison'],'baseline')
        for private in ['private-looking',self.item.url,self.padding]:self.assertNotIn(private,str(clean))

    def test_failed_attempt_does_not_retain_a_fresh_comparison_or_renew_verification(self):
        verified=self.item.verified_at
        state={};self.check(state,'<main>'+self.padding+'</main>');row=state['items'][self.item.id];before=row['body_checked_at'];hashed=row['body_hash']
        errors,_=self.check(state,'<main>점검</main>',NOW+timedelta(hours=1))
        self.assertEqual(errors[0]['category'],'parse_or_empty');self.assertEqual(row['body_status'],'failed');self.assertNotIn('body_comparison',row)
        self.assertEqual(row['body_checked_at'],before);self.assertEqual(row['body_hash'],hashed);self.assertEqual(self.item.verified_at,verified)

    def test_parser_does_not_add_requests_or_bypass_low_budget(self):
        state={};errors,calls=self.check(state,'<main>'+self.padding+'</main>')
        self.assertEqual(errors,[]);self.assertEqual(len(calls),2);self.assertEqual(cost_policy.budget.used,2)
        cost_policy.reset(3)
        with patch('benefit_monitor.collectors.rss.fetch') as fetch:
            self.assertEqual(operations.check_bodies({},[self.item],{'test':SOURCE},NOW,1),[])
        fetch.assert_not_called()

    def test_v3_migration_checks_old_scope_then_tracks_seoul_body(self):
        from benefit_monitor.collectors.body import extract_body
        self.item=benefit(url='https://mediahub.seoul.go.kr/archives/2019868')
        source=dict(SOURCE,domains=['mediahub.seoul.go.kr'])
        before='<div>조회 10</div><div class="news_detail_cont">'+self.padding+'지원 1,000원</div>'
        for changed in [False,True]:
            with self.subTest(changed=changed):
                row=dict(source='test',body_hash=operations.digest(extract_body(before)[0]),body_hash_version=3,body_target_hash=operations.digest(self.item.url))
                state={'items':{self.item.id:row}}
                current=before.replace('1,000','2,000') if changed else before
                def fetch(url,domains):
                    return b'User-agent: *\nAllow: /' if url.endswith('/robots.txt') else current.encode()
                with patch('benefit_monitor.collectors.rss.fetch',side_effect=fetch):
                    operations.check_bodies(state,[self.item],{'test':source},NOW,1)
                    self.assertEqual(row['body_comparison'],'changed' if changed else 'baseline')
                    self.assertEqual(row['body_parse_mode'],'seoul_news')
                    self.assertEqual(row['body_hash_version'],operations.BODY_HASH_VERSION)
                    current=current.replace('조회 10','조회 99')
                    operations.check_bodies(state,[self.item],{'test':source},NOW+timedelta(hours=1),1)
                    self.assertEqual(row['body_comparison'],'same')
                self.assertEqual(row.get('hold_reason'),'body_changed' if changed else None)
                clean=operations.sanitize(state|{'schema_version':1},{'test'},NOW+timedelta(hours=1))
                self.assertEqual(clean['items'][self.item.id]['body_parse_mode'],'seoul_news')
