import unittest
from copy import deepcopy
from datetime import datetime

from benefit_monitor import grocery_pick as gp

NOW = datetime.fromisoformat('2026-11-09T01:30:00+09:00')


def row(item, kind, unit, grade, today, normal, year_ago=None, day_ago=None):
    return dict(id='|'.join((item, kind, unit, grade)), item=item, kind=kind, unit=unit, grade=grade, today=today,
                day_ago=day_ago, week_ago=None, two_weeks_ago=None, year_ago=year_ago, normal=normal)


def meat(cut, label, national, unit='원/100g', species='4304', part='27'):
    return dict(id=f'{species}-{part}-{label}', cut=cut, label=label, unit=unit, national=national, seoul=None,
                min=national - 100, min_region='경남', max=national + 100, max_region='서울')


BUNDLE = dict(schema_version=1, source='groceries', fetched_at='2026-11-09T00:40:00+09:00', notice='x',
              produce=dict(survey_date='2026-11-06', items=[
                  row('배추', '가을', '1포기', '중품', 2500, 3000),
                  row('배추', '가을', '1포기', '상품', 2823, 3604),
                  row('상추', '적', '100g', '상품', 1011, 1497),
                  row('시금치', '시금치', '100g', '상품', 839, 993),
                  row('양파', '양파', '1kg', '상품', 1893, 2088),          # -9%: not cheap enough
                  row('파', '대파', '1kg', '상품', 2597, 3164),
                  row('무', '가을', '1개', '상품', 1500, None, year_ago=2000),  # no 평년: 1년전 -25%
                  row('배', '신고', '10개', '상품', 30000, 40000),
                  row('된장', '재래식', '1kg', '상품', 9000, 9000), row('김치', '포기김치', '1kg', '상품', 8000, 8000),
              ]),
              meat=dict(survey_date='2026-11-08', missing=[], items=[
                  meat('돼지 삼겹살', '삼겹살', 2768),
                  meat('한우 등심', '등심 1++등급', 15645, species='4301', part='22'),
                  meat('한우 등심', '등심 1등급', 12140, species='4301', part='22'),
              ]))

SUMMARY = '이번 주는 배추(2,823원, 평년보다 22% 쌈)와 상추가 특히 싸요. 배추전이나 겉절이로 주말 반찬을 준비하고, 상추는 삼겹살과 곁들이기 좋아요.'


def draft(summary=SUMMARY, picks=None):
    return dict(summary=summary, picks=picks if picks is not None else [
        dict(id='배추|가을|1포기|상품', menu='배추전'), dict(id='상추|적|100g|상품', menu='삼겹살 쌈'),
        dict(id='시금치|시금치|100g|상품', menu='시금치나물')])


class CandidateTests(unittest.TestCase):
    def test_cheap_produce_one_row_per_item_sorted_by_discount(self):
        host = gp.host(BUNDLE, NOW)
        produce = [c for c in host['candidates'] if c['kind'] == 'produce']
        self.assertEqual([c['name'] for c in produce], ['상추', '무', '배', '배추', '파', '시금치'])
        cabbage = next(c for c in produce if c['name'] == '배추')
        self.assertEqual((cabbage['id'], cabbage['price'], cabbage['base'], cabbage['base_price'], cabbage['pct']),
                         ('배추|가을|1포기|상품', 2823, '평년', 3604, -22))
        radish = next(c for c in produce if c['name'] == '무')
        self.assertEqual((radish['base'], radish['pct']), ('1년전', -25))
        self.assertNotIn('양파', [c['name'] for c in produce])
        self.assertEqual(host['survey_date'], '2026-11-06')

    def test_meat_is_pairing_context_without_discount(self):
        host = gp.host(BUNDLE, NOW)
        meats = [c for c in host['candidates'] if c['kind'] == 'meat']
        self.assertEqual([(c['name'], c['price']) for c in meats], [('돼지 삼겹살', 2768), ('한우 등심', 15645)])
        self.assertTrue(all('pct' not in c for c in meats))

    def test_no_host_when_fewer_than_three_cheap_items(self):
        few = deepcopy(BUNDLE)
        few['produce']['items'] = few['produce']['items'][:3]
        self.assertIsNone(gp.host(few, NOW))
        self.assertIsNone(gp.host(None, NOW))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.host = gp.host(BUNDLE, NOW)

    def ok(self, d):
        return gp.review(d, self.host, gp.known_names(BUNDLE))

    def test_accepts_grounded_summary(self):
        self.assertEqual(self.ok(draft()), [])
        # Unit text and the 1년전 base are grounded too.
        self.assertEqual(self.ok(draft('무는 1개 1,500원으로 1년전 2,000원보다 25% 싸요. 무조림이나 뭇국으로 주말 밥상을 차려 보세요.')), [])

    def test_rejects_numbers_not_belonging_to_the_preceding_item(self):
        for text in ('배추(2,900원, 평년보다 22% 쌈)와 상추가 싸요. 주말 반찬으로 좋아요.',     # wrong price
                     '배추와 상추가 30% 싸요. 주말에는 배추전과 쌈 요리를 즐겨 보세요.',          # 30 is no value of 상추
                     '이번 주 22% 싼 품목이 많아요. 배추전과 겉절이로 주말 반찬을 준비해요.'):    # number before any item
            self.assertIn('summary_number', ' '.join(self.ok(draft(text))), text)
        # Each number is checked against the item named right before it.
        self.assertEqual(self.ok(draft('상추(1,011원)와 배추는 2,823원이에요. 주말 반찬과 쌈 요리에 좋아요.')), [])

    def test_rejects_items_outside_the_candidates(self):
        errors = self.ok(draft('배추와 양파가 싸요. 배추전과 양파볶음으로 주말 반찬을 준비해 보세요.'))
        self.assertIn('summary_item', ' '.join(errors))

    def test_single_letter_names_need_a_word_boundary(self):
        # '배' inside 배추 and '무' inside 무침 are not mentions of 배/무.
        self.assertEqual(self.ok(draft('배추가 싸요. 배추무침과 겉절이로 주말 반찬을 넉넉하게 준비해 보세요.')), [])

    def test_cheap_words_only_next_to_cheap_produce(self):
        errors = self.ok(draft('상추가 싸고 삼겹살도 싸요. 상추쌈에 삼겹살을 곁들여 주말을 즐겨 보세요.'))
        self.assertIn('summary_cheap_meat', ' '.join(errors))

    def test_forbidden_claims_length_and_markup(self):
        for text, code in (('배추는 면역력에 좋아요. 배추전과 겉절이로 주말 반찬을 준비해 보세요.', 'summary_claim'),
                           ('배추가 싸요.', 'summary_length'),
                           ('배추가 싸요 <b>지금</b> 주말 반찬으로 배추전을 준비해 보세요 꼭.', 'summary_markup'),
                           ('배추가 싸요. 자세한 건 https://x.example 에서 확인하고 배추전을 만들어요.', 'summary_markup')):
            self.assertIn(code, ' '.join(self.ok(draft(text))), text)

    def test_picks_rules(self):
        base = draft()['picks']
        cases = ((base[:2], 'picks_count'),
                 (base + [dict(id='양파|양파|1kg|상품', menu='양파볶음')], 'picks_unknown'),
                 (base[:2] + [dict(base[0])], 'picks_duplicate'),
                 ([dict(base[0], menu='배추전 2인분')] + base[1:], 'picks_menu'),
                 ([base[0], dict(id='4304-27-삼겹살', menu='수육'), dict(id='4301-22-등심 1++등급', menu='구이')], 'picks_produce'))
        for picks, code in cases:
            self.assertIn(code, ' '.join(self.ok(draft(picks=picks))), code)

    def test_malformed_draft(self):
        self.assertIn('draft_shape', ' '.join(self.ok({'summary': 1})))
        self.assertIn('draft_shape', ' '.join(self.ok(None)))


class PublicTests(unittest.TestCase):
    def stored(self, **over):
        value = dict(schema_version=1, generated_at=NOW.isoformat(), survey_date='2026-11-06', source='ai',
                     summary=SUMMARY, picks=draft()['picks'])
        value.update(over)
        return value

    def test_valid_ai_pick_is_published_as_is(self):
        pick = gp.public(self.stored(), BUNDLE, [], NOW)
        self.assertEqual((pick['source'], pick['summary'], pick['picks'][0]['menu']), ('ai', SUMMARY, '배추전'))

    def test_takedown_for_that_survey_day_strips_text(self):
        takedowns = [dict(kind='grocery_pick_text', survey_date='2026-11-06', taken_down_at=NOW.isoformat(), note='')]
        pick = gp.public(self.stored(), BUNDLE, takedowns, NOW)
        self.assertEqual(pick, gp.rule_pick(gp.host(BUNDLE, NOW), NOW))  # mute -> the rule card
        other = [dict(takedowns[0], survey_date='2026-11-05')]
        self.assertEqual(gp.public(self.stored(), BUNDLE, other, NOW)['source'], 'ai')

    def test_failed_recheck_falls_back_to_rule_and_stale_day_is_dropped(self):
        tampered = gp.public(self.stored(summary='배추(9,999원)와 상추가 싸요. 주말 반찬으로 배추전을 준비해요.'), BUNDLE, [], NOW)
        self.assertEqual((tampered['source'], tampered['summary']), ('rule', None))
        self.assertEqual(len(tampered['picks']), 5)
        self.assertIsNone(gp.public(self.stored(survey_date='2026-11-05'), BUNDLE, [], NOW))
        self.assertIsNone(gp.public(self.stored(), None, [], NOW))
        self.assertIsNone(gp.public(self.stored(schema_version=2), BUNDLE, [], NOW))

    def test_rule_pick(self):
        pick = gp.rule_pick(gp.host(BUNDLE, NOW), NOW)
        self.assertEqual((pick['source'], pick['summary']), ('rule', None))
        self.assertEqual([p['id'].split('|')[0] for p in pick['picks']], ['상추', '무', '배', '배추', '파'])
        self.assertEqual(gp.public(pick, BUNDLE, [], NOW)['picks'], pick['picks'])


if __name__ == '__main__':
    unittest.main()


class WireAndTrialTests(unittest.TestCase):
    def test_schema_and_wire_round_trip(self):
        from benefit_monitor import wire_format
        host = gp.host(BUNDLE, NOW)
        schema = wire_format.schema_for('grocery', host)
        self.assertEqual(schema['properties']['picks']['items']['properties']['id'], {'type': 'string'})
        wire = dict(wire_version=wire_format.GROCERY_WIRE, **draft())
        self.assertEqual(wire_format.from_wire('grocery', wire, host), draft())
        with self.assertRaises(ValueError):
            wire_format.from_wire('grocery', dict(wire, wire_version='x'), host)

    def test_trial_accepts_only_the_host_rebuilt_from_current_groceries(self):
        import tempfile
        from pathlib import Path
        from benefit_monitor.claude_trial import validate_host, evaluate_draft
        from benefit_monitor.store import save
        host = gp.host(BUNDLE, NOW)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                validate_host(host, 'grocery', tmp)  # no groceries cache
            save(Path(tmp) / 'cache/groceries.json', BUNDLE)
            validate_host(host, 'grocery', tmp)
            forged = deepcopy(host)
            forged['candidates'][0]['price'] = 1
            with self.assertRaises(ValueError):
                validate_host(forged, 'grocery', tmp)
            with self.assertRaises(ValueError):
                validate_host(dict(host, extra=1), 'grocery', tmp)
        self.assertTrue(evaluate_draft(draft(), host, 'grocery')[1]['valid'])
        bad = evaluate_draft(draft(summary='배추(9,999원)가 싸요. 주말 반찬으로 배추전을 준비해 보세요.'), host, 'grocery')[1]
        self.assertFalse(bad['valid'])
        self.assertIn('summary_number', bad['errors'])


class RefreshTests(unittest.TestCase):
    def run_refresh(self, invoke_result=None, model=None, execute=True, days=None):
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch
        from benefit_monitor.store import save, load
        tmp = tempfile.TemporaryDirectory(dir=Path(gp.__file__).resolve().parents[1])  # project_path requires the repo
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        save(root / 'cache/groceries.json', BUNDLE)
        if days:
            save(root / 'cache/grocery_pick/days.json', days)
        calls = []

        def invoke(r, kind, path):
            calls.append((kind, json.loads(Path(path).read_text())))
            # The attempt is recorded before the paid call.
            self.assertEqual(load(root / 'cache/grocery_pick/days.json', {})['days']['2026-11-09']['status'], 'attempted')
            if model is not None:
                save(root / '.tools/claude-trial/live/runs/run1/result.json', model)
            return invoke_result or {'status': 'validated_draft', 'run_id': 'run1'}
        with patch.object(gp, 'invoke', side_effect=invoke), patch.object(gp, 'TRIAL_RUNS', root / '.tools/claude-trial/live/runs'):
            result = gp.refresh(root, NOW, execute=execute)
        return result, calls, load(root / 'cache/grocery_pick/pick.json', None)

    def test_valid_model_draft_becomes_ai_pick(self):
        result, calls, pick = self.run_refresh(model=draft())
        self.assertEqual([k for k, _ in calls], ['grocery'])
        self.assertEqual(calls[0][1], gp.host(BUNDLE, NOW))
        self.assertEqual((pick['source'], pick['summary']), ('ai', SUMMARY))
        self.assertEqual(result['source'], 'ai')

    def test_bundle_wide_names_are_rechecked_after_the_trial(self):
        # The trial gate has no bundle names; 양파 is caught here.
        bad = draft(summary='배추가 싸고 양파도 싸요. 배추전과 양파볶음으로 주말 반찬을 준비해 보세요.')
        result, _, pick = self.run_refresh(model=bad)
        self.assertEqual(pick['source'], 'rule')
        self.assertIn('summary_item', result['errors'])

    def test_rejected_or_credit_exhausted_falls_back_to_rule(self):
        for status in ('rejected_draft', 'credit_exhausted', 'stopped_before_result'):
            result, _, pick = self.run_refresh(invoke_result={'status': status, 'run_id': None})
            self.assertEqual(pick['source'], 'rule', status)
            self.assertEqual(result['model']['status'], status)

    def test_one_attempt_per_day_and_no_spend_without_execute(self):
        _, calls, pick = self.run_refresh(execute=False)
        self.assertEqual((calls, pick['source']), ([], 'rule'))
        _, calls, _ = self.run_refresh(days={'days': {'2026-11-09': {'status': 'attempted'}}})
        self.assertEqual(calls, [])


class PublicationPathTests(unittest.TestCase):
    def stored(self):
        return dict(schema_version=1, generated_at=NOW.isoformat(), survey_date='2026-11-06', source='ai',
                    summary=SUMMARY, picks=draft()['picks'])

    def test_publish_attaches_rechecked_pick_and_applies_the_mute(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from benefit_monitor import publish, auto_release
        from benefit_monitor.store import save
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root / 'cache/groceries.json', BUNDLE)
            save(root / 'cache/grocery_pick/pick.json', self.stored())
            with patch.object(auto_release, 'load', return_value=({}, [])):
                data = {}
                publish.attach_groceries(root, data, NOW)
            self.assertEqual(data['grocery_pick']['source'], 'ai')
            mute = [dict(kind='grocery_pick_text', survey_date='2026-11-06', taken_down_at=NOW.isoformat(), note='')]
            with patch.object(auto_release, 'load', return_value=({}, mute)):
                data = {}
                publish.attach_groceries(root, data, NOW)
            self.assertEqual((data['grocery_pick']['source'], data['grocery_pick']['summary']), ('rule', None))

    def test_admin_redeploy_mutes_the_text_without_touching_prices(self):
        from benefit_monitor.auto_release import apply_takedowns
        data = {'items': [], 'groceries': BUNDLE, 'grocery_pick': self.stored()}
        mute = [dict(kind='grocery_pick_text', survey_date='2026-11-06', taken_down_at=NOW.isoformat(), note='')]
        clean = apply_takedowns(data, mute)
        self.assertEqual(clean['grocery_pick'], gp.rule_pick(gp.host(BUNDLE, NOW), NOW))
        self.assertEqual(clean['groceries'], BUNDLE)
        self.assertEqual(apply_takedowns(data, [])['grocery_pick']['source'], 'ai')


class ReviewFollowUpTests(unittest.TestCase):
    """Code review 2026-11-09: cases the first gate let through."""
    def setUp(self):
        self.host = gp.host(BUNDLE, NOW)

    def ok(self, d):
        return gp.review(d, self.host, gp.known_names(BUNDLE))

    def test_generic_meat_words_cannot_be_called_cheap(self):
        for text in ('배추(2,823원, 평년보다 22% 쌈)로 겉절이를 담가 보세요. 돼지고기도 저렴해요.',
                     '이번 주는 닭고기와 소고기가 싸요. 배추전과 상추쌈으로 주말을 즐겨 보세요.'):
            self.assertIn('summary_cheap_meat', ' '.join(self.ok(draft(text))), text)

    def test_one_letter_names_before_more_particles(self):
        # 배 is a candidate here; 양파 is not, and the strict rule rejects naming it at all.
        self.assertIn('summary_item', ' '.join(self.ok(draft('양파가 좋아요. 배까지 싸게 나왔으니 주말 간식으로 사 두세요.'))))

    def test_non_candidate_names_are_rejected_as_approved(self):
        self.assertIn('summary_item', ' '.join(self.ok(draft('배추가 특히 싸요. 배추는 된장국이나 김치찌개에 넣어 주말 밥상을 차려 보세요.'))))

    def test_menus_follow_the_claim_ban(self):
        picks = draft()['picks']
        picks[0] = dict(picks[0], menu='다이어트 샐러드')
        self.assertIn('picks_menu', ' '.join(self.ok(draft(picks=picks))))

    def test_percent_rounds_half_up_like_the_browser(self):
        bundle = deepcopy(BUNDLE)
        bundle['produce']['items'].append(row('가지', '가지', '1개', '상품', 750, 1200))   # -37.5
        bundle['produce']['items'].append(row('오이', '다다기', '10개', '상품', 905, 1000))  # -9.5
        rows = {c['name']: c for c in gp.host(bundle, NOW)['candidates']}
        self.assertEqual(rows['가지']['pct'], -37)  # Math.round(-37.5) == -37
        self.assertNotIn('오이', rows)             # Math.round(-9.5) == -9: not cheap

    def test_mute_gives_the_same_rule_card_on_both_publish_paths(self):
        from benefit_monitor.auto_release import apply_takedowns
        stored = dict(schema_version=1, generated_at=NOW.isoformat(), survey_date='2026-11-06', source='ai', summary=SUMMARY,
                      picks=draft()['picks'][:2] + [dict(id='4304-27-삼겹살', menu='수육')])
        mute = [dict(kind='grocery_pick_text', survey_date='2026-11-06', taken_down_at=NOW.isoformat(), note='')]
        via_publish = gp.public(stored, BUNDLE, mute, NOW)
        via_admin = apply_takedowns({'items': [], 'groceries': BUNDLE, 'grocery_pick': stored}, mute)['grocery_pick']
        self.assertEqual(via_publish, via_admin)
        self.assertEqual(via_publish, gp.rule_pick(gp.host(BUNDLE, NOW), NOW))

    def test_schema_is_stable_across_days(self):
        from benefit_monitor import wire_format
        other = deepcopy(BUNDLE)
        other['produce']['items'] = [r for r in other['produce']['items'] if r['item'] != '상추']  # different candidates
        self.assertEqual(wire_format.schema_for('grocery', gp.host(BUNDLE, NOW)),
                         wire_format.schema_for('grocery', gp.host(other, NOW)))
