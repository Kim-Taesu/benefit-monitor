import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import wire_format as w
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


def wire(**facts):
    base = {field: {'status': 'unknown', 'unknown_reason': '원문에 없음'} for field in w.FIELDS}
    base.update(facts)
    return dict(wire_version=w.RESEARCH_WIRE, status='completed', errors=[],
                records=[dict(candidate_id='c1', research_status='completed', stop_reason='sufficient_evidence', facts=base)])


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
        self.assertEqual(set(schema['$defs']), {'evidence', 'unknown'})
        self.assertEqual(text.count('"unknown_reason": {'), 1)
        sample = wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s4'}]},
                      event_period={'status': 'supported', 'value': {'start': '2026-11-07', 'end': ''},
                                    'evidence': [{'segment_id': 'd1s1'}]})
        self.assertTrue(conforms(sample, schema, schema))
        bad = [wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': []}),
               wire(availability={'status': 'supported', 'value': 'x', 'evidence': [{'segment_id': 'd1s1'}]}),
               wire(event_period={'status': 'supported', 'value': {'start': '11월 7일', 'end': ''},
                                  'evidence': [{'segment_id': 'd1s1'}]}),
               wire(selection={'status': 'unknown'})]
        for value in bad:
            self.assertFalse(conforms(value, schema, schema))

    def test_schema_is_static_and_inside_provider_limits(self):
        schema = w.research_wire_schema()
        self.assertEqual(schema, w.research_wire_schema())
        found = w.limits(schema)
        self.assertLessEqual(found['unions'], w.UNION_LIMIT)
        self.assertEqual(found['optional'], 0)
        self.assertEqual(found['unsupported'], [])
        self.assertNotIn('minLength', json.dumps(schema))
        self.assertEqual(set(schema['properties']['records']['items']['properties']['facts']['properties']), set(w.FIELDS))

    def test_over_limit_schema_is_refused(self):
        many = {'type': 'object', 'additionalProperties': False, 'required': [],
                'properties': {str(i): {'type': ['string', 'null']} for i in range(17)}}
        with self.assertRaises(ValueError):
            w.check_limits(many)
        with self.assertRaises(ValueError):
            w.check_limits({'type': 'string', 'minLength': 1})

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

    def test_unknown_segment_wrong_version_and_empty_reason_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'segment'):
            w.research_from_wire(wire(fee_status={'status': 'supported', 'value': 'free', 'evidence': [{'segment_id': 'd1s99'}]}), host())
        with self.assertRaisesRegex(ValueError, 'version'):
            w.research_from_wire(dict(wire(), wire_version='research-extraction-v3'), host())
        draft = w.research_from_wire(wire(cost_details={'status': 'unknown', 'unknown_reason': '  '}), host())
        with self.assertRaisesRegex(ValueError, 'reason'):
            evaluate_draft(draft, host(), 'research')

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
        self.assertEqual(w.limits(schema)['unions'], 1)
        branches = schema['properties']['topics']['items']['anyOf']
        self.assertEqual([b['properties']['topic_id']['enum'] for b in branches], [['culture'], ['family']])
        self.assertEqual(json.dumps(schema).count('"reason": {"type": "string"}, "match_type"'), 2)
        sample = dict(wire_version=w.TOPIC_WIRE, status='completed', errors=[], excluded_items=[],
                      topics=[dict(topic_id='family', item_links=[dict(item_id='b', reason='r', match_type='explicit')],
                                   excluded_items=[dict(item_id='a', reason='가족 근거 없음')])])
        self.assertTrue(conforms(sample, schema, schema))
        sample['topics'][0]['item_links'][0]['item_id'] = 'a'
        self.assertFalse(conforms(sample, schema, schema))

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
        answer['topics'] = [dict(topic_id='culture', item_links=[link], excluded_items=[{'item_id': 'a', 'reason': '무관'}])]
        _, report = evaluate_draft(w.topic_from_wire(answer, topic_host()), topic_host(), 'topic')
        self.assertFalse(report['valid'])


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


if __name__ == '__main__':
    unittest.main()
