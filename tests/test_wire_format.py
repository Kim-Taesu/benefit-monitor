import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import wire_format as w
from benefit_monitor.ai_contract import validate
from benefit_monitor.claude_trial import ClaudeClient, evaluate_draft
from benefit_monitor.trial_budget import TrialBudget

ROOT = Path(__file__).resolve().parents[1]
BODY = '서울 가족 미술 체험.\n대상: 유아 동반 가족 대상 프로그램입니다. 참가비는 1.5만 원입니다!\n\n관람료는 무료입니다.'


def host(body=BODY):
    doc = dict(id='doc-a', source_id='seoul', requested_url='https://www.seoul.go.kr/a', final_url='https://www.seoul.go.kr/a',
               publisher_type='issuer', document_role='notice', retrieved_at='2026-11-05T12:00:00+09:00', published_at=None,
               body_hash=hashlib.sha256(body.encode()).hexdigest(), hash_algorithm='sha256-utf8-exact',
               extraction_scope='test', fetch_status='ok', body=body)
    return dict(mode='api_agent', synthetic=False, now='2026-11-05T12:00:00+09:00', output_schema_version='research-draft-v1',
                budget={}, candidates=[dict(candidate_id='c1', source_id='seoul', document_ids=['doc-a'])], documents=[doc])


def slots(field, given):
    """Readable test facts (status/value/evidence) mapped onto the generic wire slots."""
    out = dict(field=field, status=given.get('status', 'unknown'), text='', items=[], not_confirmed=[], start='', end='',
               number=0, segment_ids=[e['segment_id'] for e in given.get('evidence', [])],
               unknown_reason=given.get('unknown_reason', ''))
    value = given.get('value')
    if value is not None:
        if field == 'eligibility':
            out.update(text=value['scope'], items=value['required'], not_confirmed=value['not_confirmed'])
        elif field in ('event_period', 'application_period'):
            out.update(start=value['start'], end=value['end'])
        elif field == 'published_at':
            out['start'] = value
        elif field == 'capacity':
            out['number'] = value
        elif field == 'districts':
            out['items'] = value
        else:
            out['text'] = value
    return out


def wire(**facts):
    rows = [slots(field, facts.get(field, {'unknown_reason': '원문에 없음'})) for field in w.FIELDS]
    return dict(wire_version=w.RESEARCH_WIRE, status='completed', errors=[],
                records=[dict(candidate_id='c1', research_status='completed', stop_reason='sufficient_evidence', facts=rows)])


def conforms(value, node, root):
    """Small validator for the keywords the wire schemas use; refs must resolve inside $defs."""
    if '$ref' in node:
        prefix = '#/$defs/'
        assert node['$ref'].startswith(prefix), node['$ref']
        return conforms(value, root['$defs'][node['$ref'][len(prefix):]], root)
    if 'anyOf' in node:
        return any(conforms(value, branch, root) for branch in node['anyOf'])
    if 'enum' in node:
        return value in node['enum']
    kind = node.get('type')
    if kind == 'object':
        return (isinstance(value, dict) and set(value) == set(node['properties']) == set(node['required'])
                and all(conforms(value[k], v, root) for k, v in node['properties'].items()))
    if kind == 'array':
        return (isinstance(value, list) and len(value) >= node.get('minItems', 0)
                and all(conforms(item, node['items'], root) for item in value))
    if kind == 'string':
        import re
        return isinstance(value, str) and ('pattern' not in node or re.search(node['pattern'], value) is not None)
    if kind == 'integer':
        return type(value) is int
    raise AssertionError('unexpected schema node: ' + json.dumps(node))


class ResearchWireTests(unittest.TestCase):
    def test_shared_shapes_use_resolvable_defs_and_samples_conform(self):
        schema = w.research_wire_schema()
        text = json.dumps(schema)
        self.assertNotIn('$defs', schema)
        self.assertNotIn('anyOf', text)
        self.assertLess(len(text), 2500)
        self.assertNotIn('pattern', text)
        sample = wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s4'}]},
                      event_period={'status': 'supported', 'value': {'start': '2026-11-07', 'end': ''},
                                    'evidence': [{'segment_id': 'd1s1'}]})
        self.assertTrue(conforms(sample, schema, schema))
        broken = wire()
        del broken['records'][0]['facts'][0]['unknown_reason']
        renamed = wire()
        renamed['records'][0]['facts'][0]['field'] = 'age_limit'
        for value in (broken, renamed):
            self.assertFalse(conforms(value, schema, schema))

    def test_constraints_moved_out_of_the_grammar_are_host_rejections(self):
        cases = {'evidence': wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': []}),
                 'period format': wire(event_period={'status': 'supported', 'value': {'start': '11월 7일', 'end': ''},
                                                     'evidence': [{'segment_id': 'd1s1'}]}),
                 'districts': wire(districts={'status': 'supported', 'value': [], 'evidence': [{'segment_id': 'd1s1'}]}),
                 'availability': wire(availability={'status': 'supported', 'value': 'x', 'evidence': [{'segment_id': 'd1s1'}]}),
                 'fee_status': wire(fee_status={'status': 'supported', 'value': 'maybe', 'evidence': [{'segment_id': 'd1s4'}]}),
                 'scope': wire(eligibility={'status': 'supported', 'evidence': [{'segment_id': 'd1s2'}],
                                            'value': {'scope': 'everyone', 'required': [], 'not_confirmed': []}}),
                 'empty': wire(selection={'status': 'supported', 'value': ' ', 'evidence': [{'segment_id': 'd1s1'}]})}
        district = wire(districts={'status': 'supported', 'value': ['강남'], 'evidence': [{'segment_id': 'd1s1'}]})
        cases['district names'] = district
        duplicate = wire()
        duplicate['records'][0]['facts'].append(dict(duplicate['records'][0]['facts'][0]))
        missing = wire()
        missing['records'][0]['facts'].pop()
        cases['duplicate'] = duplicate
        cases['missing'] = missing
        schema = w.research_wire_schema()
        for message, value in cases.items():
            self.assertTrue(conforms(value, schema, schema), message)
            with self.assertRaisesRegex(ValueError, message):
                w.research_from_wire(value, host())

    def test_application_period_accepts_a_date_without_a_time(self):
        # 2026-11-14: notices mostly give the deadline as a date only, and the model wrote that date even
        # though the prompt asked for unknown; the whole answer was then thrown away. The host now reads
        # a date as that whole day (KST) and never shows a time nobody wrote (see auto_publish._end_point).
        def period(start, end):
            draft = w.research_from_wire(wire(application_period={'status': 'supported', 'value': {'start': start, 'end': end},
                                                                  'evidence': [{'segment_id': 'd1s1'}]}), host())
            _, report = evaluate_draft(draft, host(), 'research')
            self.assertTrue(report['structural_valid'], report)
            return {f['field']: f for f in draft['records'][0]['facts']}['application_period']['value']
        self.assertEqual(period('2026-11-07', '2026-11-23'),
                         {'start': '2026-11-07T00:00:00+09:00', 'end': '2026-11-23T23:59:59+09:00'})
        self.assertEqual(period('', '2026-11-23'), {'start': None, 'end': '2026-11-23T23:59:59+09:00'})
        self.assertEqual(period('2026-11-07T09:00+09:00', '2026-11-23'),
                         {'start': '2026-11-07T09:00+09:00', 'end': '2026-11-23T23:59:59+09:00'})
        self.assertEqual(period('2026-11-07T09:00+09:00', '2026-11-19T17:00+09:00'),
                         {'start': '2026-11-07T09:00+09:00', 'end': '2026-11-19T17:00+09:00'})
        for bad in ('11월 23일', '2026-13-40', '2026-11-23 18:00', '2026-11-23T18:00'):
            with self.assertRaisesRegex(ValueError, 'invalid period format'):
                w.research_from_wire(wire(application_period={'status': 'supported', 'value': {'start': '', 'end': bad},
                                                              'evidence': [{'segment_id': 'd1s1'}]}), host())
        # event_period stays a plain date.
        with self.assertRaisesRegex(ValueError, 'invalid period format'):
            w.research_from_wire(wire(event_period={'status': 'supported', 'value': {'start': '', 'end': '2026-11-23T18:00+09:00'},
                                                    'evidence': [{'segment_id': 'd1s1'}]}), host())

    def test_unknown_without_a_reason_gets_a_host_reason(self):
        # 2026-11-14: one empty unknown_reason used to reject every other fact of the answer. An unknown
        # carries no value either way, so the host fills the reason in and keeps the rest.
        value = wire(selection={'status': 'unknown', 'unknown_reason': ' '},
                     fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s4'}]})
        for fact in value['records'][0]['facts']:
            if fact['field'] == 'eligibility':
                fact.update(text='unrestricted', unknown_reason='')  # Stray value on an unknown: dropped.
        draft = w.research_from_wire(value, host())
        facts = {f['field']: f for f in draft['records'][0]['facts']}
        self.assertEqual((facts['selection']['status'], facts['selection']['unknown_reason']), ('unknown', w.NO_REASON))
        self.assertEqual((facts['eligibility']['value'], facts['eligibility']['unknown_reason']), (None, w.NO_REASON))
        self.assertEqual(facts['fee_status']['value'], 'free')
        _, report = evaluate_draft(draft, host(), 'research')
        self.assertTrue(report['structural_valid'], report)

    def test_published_at_requires_date_and_segment(self):
        ok = w.research_from_wire(wire(published_at={'status': 'supported', 'value': '2026-10-30',
                                                     'evidence': [{'segment_id': 'd1s1'}]}), host())
        facts = {f['field']: f for f in ok['records'][0]['facts']}
        self.assertEqual(facts['published_at']['value'], '2026-10-30')
        self.assertEqual(facts['published_at']['evidence'][0]['source_ref'], 'doc-a')
        _, report = evaluate_draft(ok, host(), 'research')
        self.assertTrue(report['structural_valid'], report)
        for bad in ('10월 30일', ''):
            with self.assertRaisesRegex(ValueError, 'invalid period format'):
                w.research_from_wire(wire(published_at={'status': 'supported', 'value': bad,
                                                        'evidence': [{'segment_id': 'd1s1'}]}), host())
        with self.assertRaisesRegex(ValueError, 'evidence'):
            w.research_from_wire(wire(published_at={'status': 'supported', 'value': '2026-10-30', 'evidence': []}), host())
        unknown = w.research_from_wire(wire(), host())
        self.assertNotIn('published_at', {f['field'] for f in unknown['records'][0]['facts']})

    def test_published_at_end_slot_is_rejected(self):
        value = wire(published_at={'status': 'supported', 'value': '2026-10-30', 'evidence': [{'segment_id': 'd1s1'}]})
        for fact in value['records'][0]['facts']:
            if fact['field'] == 'published_at':
                fact['end'] = '2026-10-31'
        with self.assertRaisesRegex(ValueError, 'invalid period format'):
            w.research_from_wire(value, host())

    def test_multi_document_segments_map_to_their_document(self):
        base = host()
        second = dict(base['documents'][0], id='doc-b', body='게시일 2026-10-30. 참가비는 무료입니다.')
        second['body_hash'] = hashlib.sha256(second['body'].encode()).hexdigest()
        base['documents'].append(second)
        base['candidates'][0]['document_ids'] = ['doc-a', 'doc-b']
        draft = w.research_from_wire(wire(fee_status={'status': 'supported', 'value': 'free',
                                                      'evidence': [{'segment_id': 'd1s4'}, {'segment_id': 'd2s2'}]}), base)
        fee = {f['field']: f for f in draft['records'][0]['facts']}['fee_status']
        self.assertEqual([(e['source_ref'], e['locator']) for e in fee['evidence']], [('doc-a', 'd1s4'), ('doc-b', 'd2s2')])
        _, report = evaluate_draft(draft, base, 'research')
        self.assertTrue(report['structural_valid'], report)

    def test_citing_a_subset_of_documents_is_valid_but_foreign_sources_are_not(self):
        body = '행사는 2026-12-01부터 2026-12-31까지 열립니다.\n신청은 현장에서 합니다.'
        base = host(body)
        second = dict(base['documents'][0], id='doc-b')
        base['documents'].append(second)
        base['candidates'][0]['document_ids'] = ['doc-a', 'doc-b']
        ev = [{'segment_id': 'd1s1'}]
        facts = {f: {'status': 'supported', 'value': 'x', 'evidence': ev} for f in w.TEXT_FIELDS}
        facts.update(fee_status={'status': 'supported', 'value': 'paid', 'evidence': ev},
                     eligibility={'status': 'supported', 'value': {'scope': 'unrestricted', 'required': [], 'not_confirmed': []}, 'evidence': ev},
                     event_period={'status': 'supported', 'value': {'start': '2026-12-01', 'end': '2026-12-31'}, 'evidence': ev},
                     application_period={'status': 'supported', 'value': {'start': '2026-11-01T09:00+09:00', 'end': ''}, 'evidence': ev},
                     capacity={'status': 'supported', 'value': 10, 'evidence': ev})
        facts['availability'] = {'unknown_reason': '실시간 확인 필요'}
        draft = w.research_from_wire(wire(**facts), base)
        report = evaluate_draft(draft, base, 'research')[1]
        self.assertTrue(report['structural_valid'], report)
        full = evaluate_draft(draft, base, 'research')[0]
        foreign = dict(base['documents'][0], id='doc-z')
        base['documents'].append(foreign)
        source = {k: foreign[k] for k in full['records'][0]['sources'][0]}
        full['records'][0]['sources'].append(source)
        result = validate(full, base, 'research')
        self.assertFalse(result['valid'])
        self.assertIn('document belongs to another candidate', result['errors'])

    def test_unknown_fact_value_and_evidence_are_discarded(self):
        draft = w.research_from_wire(wire(capacity={'status': 'unknown', 'value': 99, 'evidence': [{'segment_id': 'd1s1'}],
                                                    'unknown_reason': '정원 미기재'}), host())
        facts = {f['field']: f for f in draft['records'][0]['facts']}
        self.assertEqual((facts['capacity']['value'], facts['capacity']['evidence']), (None, []))
        self.assertEqual(facts['capacity']['unknown_reason'], '정원 미기재')
        self.assertNotIn('summary', facts)

    def test_schema_is_static_and_inside_provider_limits(self):
        schema = w.research_wire_schema()
        self.assertEqual(schema, w.research_wire_schema())
        found = w.limits(schema)
        self.assertEqual((found['unions'], found['patterns']), (0, 0))
        self.assertEqual(found['optional'], 0)
        self.assertEqual(found['unsupported'], [])
        self.assertNotIn('minLength', json.dumps(schema))
        fact = schema['properties']['records']['items']['properties']['facts']['items']
        self.assertEqual(fact['properties']['field']['enum'], list(w.FIELDS))

    def test_over_limit_schema_is_refused(self):
        many = {'type': 'object', 'additionalProperties': False, 'required': [],
                'properties': {str(i): {'type': ['string', 'null']} for i in range(17)}}
        with self.assertRaises(ValueError):
            w.check_limits(many)
        with self.assertRaises(ValueError):
            w.check_limits({'type': 'string', 'minLength': 1})
        with self.assertRaisesRegex(ValueError, 'patterns'):
            w.check_limits({'type': 'string', 'pattern': '^a$'})
        with self.assertRaisesRegex(ValueError, 'unions'):
            w.check_limits({'anyOf': [{'type': 'string'}, {'type': 'integer'}]})

    def test_segments_are_exact_slices_and_keep_decimals(self):
        rows = w.segments(BODY, 'd1')
        self.assertTrue(all(r['text'] in BODY for r in rows))
        self.assertEqual([r['id'] for r in rows], ['d1s1', 'd1s2', 'd1s3', 'd1s4'])
        self.assertIn('참가비는 1.5만 원입니다!', [r['text'] for r in rows])

    def test_model_input_replaces_body_without_touching_host(self):
        original = host()
        sent = w.research_model_input(original)
        self.assertIn('body', original['documents'][0])
        self.assertNotIn('body', sent['documents'][0])
        self.assertEqual(sent['documents'][0]['segments'][0]['id'], 'd1s1')

    def test_host_builds_exact_quotes_and_v3_gates_still_run(self):
        draft = w.research_from_wire(wire(
            fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s4'}, {'segment_id': 'd1s4'}]},
            eligibility={'status': 'supported', 'value': {'scope': 'restricted', 'required': ['유아 동반 가족'], 'not_confirmed': []},
                         'evidence': [{'segment_id': 'd1s2'}]},
            event_period={'status': 'supported', 'value': {'start': '2026-11-07', 'end': ''}, 'evidence': [{'segment_id': 'd1s1'}]}),
            host())
        facts = {f['field']: f for f in draft['records'][0]['facts']}
        self.assertEqual(facts['fee_status']['evidence'], [{'source_ref': 'doc-a', 'quote': '관람료는 무료입니다.', 'locator': 'd1s4'}])
        self.assertEqual(facts['event_period']['value'], {'start': '2026-11-07', 'end': None})
        self.assertNotIn('summary', facts)
        self.assertEqual(facts['availability']['status'], 'unknown')
        _, report = evaluate_draft(draft, host(), 'research')
        self.assertTrue(report['valid'], report)

    def test_restriction_cue_gate_is_not_bypassed(self):
        draft = w.research_from_wire(wire(eligibility={'status': 'supported', 'evidence': [{'segment_id': 'd1s1'}],
                                                       'value': {'scope': 'unrestricted', 'required': [], 'not_confirmed': []}}), host())
        _, report = evaluate_draft(draft, host(), 'research')
        self.assertFalse(report['valid'])
        self.assertIn('unrestricted_with_restriction', [f['code'] for f in report['coverage']['findings']])

    def test_unknown_segment_and_wrong_version_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'segment'):
            w.research_from_wire(wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s99'}]}), host())
        with self.assertRaisesRegex(ValueError, 'version'):
            w.research_from_wire(dict(wire(), wire_version='research-extraction-v3'), host())

    def test_invalid_date_is_still_rejected_by_existing_gate(self):
        draft = w.research_from_wire(wire(event_period={'status': 'supported', 'value': {'start': '2026-13-40', 'end': ''},
                                                        'evidence': [{'segment_id': 'd1s1'}]}), host())
        with self.assertRaises(ValueError):
            evaluate_draft(draft, host(), 'research')


def topic_host():
    items, claims = [], []
    for item_id, topics, facets in (('a', ['culture'], []), ('b', ['culture', 'family'], ['family']),
                                    ('c', ['family'], []), ('d', ['shopping'], [])):
        claims.append({'id': 'claim-' + item_id, 'item_id': item_id, 'field': 'summary', 'value': item_id})
        items.append({'item_id': item_id, 'display_eligible': True, 'claim_ids': ['claim-' + item_id],
                      'topic_basis': {'topic_ids': topics, 'title_facets': facets, 'evidence_claim_ids': ['claim-' + item_id]}})
    return dict(mode='api_agent', synthetic=False, now='2026-11-05T12:00:00+09:00', snapshot_id='snap', approved_items=items,
                approved_claims=claims, excluded_items=[], allowed_topic_ids=['culture', 'family', 'career'], previous_topics=[])


class TopicWireTests(unittest.TestCase):
    def test_branches_allow_only_basis_supported_items(self):
        choices = w.eligible_items(topic_host())
        self.assertEqual(choices, {'culture': ['a', 'b'], 'family': ['b']})
        schema = w.topic_wire_schema(topic_host())
        self.assertEqual(w.limits(schema)['unions'], 0)
        card = schema['properties']['topics']['items']
        self.assertEqual(card['properties']['topic_id']['enum'], ['culture', 'family'])
        self.assertEqual(card['properties']['item_links']['items']['properties']['item_id']['enum'], ['a', 'b'])
        sample = dict(wire_version=w.TOPIC_WIRE, status='completed', errors=[], excluded_items=[],
                      topics=[dict(topic_id='family', item_links=[dict(item_id='b', reason='r', match_type='explicit')],
                                   excluded_items=[dict(item_id='a', reason='가족 근거 없음')])])
        self.assertTrue(conforms(sample, schema, schema))
        sample['topics'][0]['item_links'][0]['item_id'] = 'c'
        self.assertFalse(conforms(sample, schema, schema))
        sample['topics'][0]['item_links'][0]['item_id'] = 'a'
        self.assertTrue(conforms(sample, schema, schema))
        with self.assertRaisesRegex(ValueError, 'not eligible'):
            w.topic_from_wire(sample, topic_host())

    def test_no_eligible_topic_stops_before_any_request(self):
        empty = topic_host()
        empty['allowed_topic_ids'] = ['career']
        with self.assertRaisesRegex(ValueError, 'no topic'):
            w.topic_wire_schema(empty)

    def test_host_fills_title_snapshot_and_claims_then_gates_run(self):
        answer = dict(wire_version=w.TOPIC_WIRE, status='completed', errors=[], excluded_items=[],
                      topics=[dict(topic_id='family', excluded_items=[],
                                   item_links=[dict(item_id='b', reason='가족 참여 프로그램', match_type='explicit')])])
        draft = w.topic_from_wire(answer, topic_host())
        card = draft['topics'][0]
        self.assertEqual((card['title'], card['snapshot_id']), ('가족과 함께', 'snap'))
        self.assertEqual(card['item_links'][0]['evidence_claim_ids'], ['claim-b'])
        self.assertEqual(card['profile_conditions'], [])
        _, report = evaluate_draft(draft, topic_host(), 'topic')
        self.assertTrue(report['valid'], report)

    def test_duplicate_topic_and_included_excluded_conflict_are_rejected(self):
        link = dict(item_id='a', reason='전시', match_type='explicit')
        answer = dict(wire_version=w.TOPIC_WIRE, status='completed', errors=[], excluded_items=[],
                      topics=[dict(topic_id='culture', item_links=[link], excluded_items=[]),
                              dict(topic_id='culture', item_links=[link], excluded_items=[])])
        _, report = evaluate_draft(w.topic_from_wire(answer, topic_host()), topic_host(), 'topic')
        self.assertFalse(report['valid'])
        # Included in a card wins over an exclusion of the same item (card-level or top-level).
        answer['topics'] = [dict(topic_id='culture', item_links=[link], excluded_items=[{'item_id': 'a', 'reason': '무관'}])]
        answer['excluded_items'] = [{'item_id': 'a', 'reason': '다른 주제'}, {'item_id': 'd', 'reason': '무관'}]
        draft = w.topic_from_wire(answer, topic_host())
        self.assertEqual(draft['topics'][0]['excluded_items'], [])
        self.assertEqual([x['item_id'] for x in draft['excluded_items']], ['d'])
        _, report = evaluate_draft(draft, topic_host(), 'topic')
        self.assertTrue(report['valid'], report)


class RequestShapeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.budget = TrialBudget.initialize(self.root/'budget.json', 'claude-haiku-5-5', '0.10', '0.50')

    def test_schema_goes_in_output_config_and_over_limit_costs_nothing(self):
        sent = []
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): return False
        def transport(request):
            sent.append(json.loads(request.data))
            return Response(json.dumps({'model': 'claude-haiku-5-5', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{}'}],
                                        'usage': {'input_tokens': 10, 'output_tokens': 5}}).encode())
        client = ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')
        with patch('benefit_monitor.claude_trial.network_open', side_effect=transport):
            client.message('s', 'u', output_schema=w.research_wire_schema())
        self.assertEqual(sent[0]['output_config']['format']['type'], 'json_schema')
        self.assertEqual(sent[0]['thinking'], {'type': 'disabled'})
        bad = {'type': 'string', 'minLength': 1}
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('must not send')):
            with self.assertRaises(ValueError):
                client.message('s', 'u2', output_schema=bad)
        self.assertEqual(self.budget.summary()['request_count'], 1)



class PickWireTests(unittest.TestCase):
    """Festival and benefit picks share one plain schema shape (2026-11-14)."""

    def test_pick_schemas_round_trip_and_reject_other_versions(self):
        for kind, version in (('festival', w.FESTIVAL_WIRE), ('benefit', w.BENEFIT_WIRE)):
            schema = w.schema_for(kind, None)
            self.assertEqual(list(schema['properties']), ['wire_version', 'summary', 'picks'])
            self.assertEqual(w.limits(schema), {'unions': 0, 'optional': 0, 'patterns': 0, 'unsupported': []})
            draft = {'summary': '요약', 'picks': [{'id': 'a', 'line': '줄'}]}
            self.assertEqual(w.from_wire(kind, dict(draft, wire_version=version), None), draft)
            other = w.BENEFIT_WIRE if kind == 'festival' else w.FESTIVAL_WIRE
            with self.assertRaises(ValueError):
                w.from_wire(kind, dict(draft, wire_version=other), None)
            with self.assertRaises(ValueError):
                w.from_wire(kind, dict(draft, wire_version=version, extra=1), None)


if __name__ == '__main__':
    unittest.main()
