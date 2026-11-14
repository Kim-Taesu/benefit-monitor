"""Per-kind model contracts (2026-11-14): one registry row per kind, a fingerprint that follows that
kind only, and request variants that never change the regular request."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import claude_trial as trial, wire_format
from benefit_monitor.trial_budget import TrialBudget

ROOT = Path(__file__).resolve().parents[1]


class RegistryTests(unittest.TestCase):
    def test_every_kind_has_prompt_task_schema_and_decoder(self):
        self.assertEqual(set(trial.KINDS), set(wire_format.WIRES))
        for kind, row in trial.KINDS.items():
            with self.subTest(kind=kind):
                self.assertTrue((ROOT/'docs/ai/prompts'/row.prompt).is_file())
                self.assertTrue(row.task.startswith('위 `<input>`'))
                version, schema, from_wire, decoders = wire_format.WIRES[kind]
                self.assertEqual(wire_format.schema_for(kind, None)['properties']['wire_version']['enum'], [version])
                self.assertTrue(callable(from_wire))
        self.assertEqual(trial.TASKS, {k: r.task for k, r in trial.KINDS.items()})
        self.assertEqual(trial.SYSTEM_PROMPTS, {k: r.prompt for k, r in trial.KINDS.items()})

    def test_every_schema_is_static(self):
        # A schema that follows the day's data compiles a new grammar and pays a new probe each day.
        for kind in trial.KINDS:
            self.assertEqual(wire_format.schema_for(kind, None), wire_format.schema_for(kind, None), kind)
            wire_format.check_limits(wire_format.schema_for(kind, None))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(KeyError):
            trial.evaluate_draft({}, {}, 'unknown')
        with self.assertRaises(KeyError):
            trial.validate_host({}, 'unknown', ROOT)


class ContractFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT/'docs/ai/prompts', self.root/'docs/ai/prompts')

    def all(self):
        return {kind: trial.contract_fingerprint(self.root, kind) for kind in trial.KINDS}

    def changed(self, before):
        after = self.all()
        return {kind for kind in before if before[kind] != after[kind]}

    def test_matches_repository_and_is_distinct_per_kind(self):
        values = self.all()
        self.assertEqual(values, {kind: trial.contract_fingerprint(ROOT, kind) for kind in trial.KINDS})
        self.assertEqual(len(set(values.values())), len(values))

    def test_own_prompt_changes_only_that_kind(self):
        before = self.all()
        path = self.root/'docs/ai/prompts/festival-system.md'
        path.write_text(path.read_text() + '\n추가 규칙\n')
        self.assertEqual(self.changed(before), {'festival'})

    def test_task_line_and_schema_are_covered(self):
        before = self.all()
        with patch.object(trial.KINDS['grocery'], 'task', trial.KINDS['grocery'].task + ' 추가'):
            self.assertEqual(self.changed(before), {'grocery'})
        row = wire_format.WIRES['health']
        changed = (row[0], lambda host: dict(row[1](host), title='changed'), row[2], row[3])
        with patch.dict(wire_format.WIRES, {'health': changed}):
            self.assertEqual(self.changed(before), {'health'})

    def test_decoder_source_is_covered_for_its_kinds_only(self):
        before = self.all()
        def other(wire, version):
            return wire
        for kind in ('festival', 'benefit'):
            row = wire_format.WIRES[kind]
            with patch.dict(wire_format.WIRES, {kind: (row[0], row[1], row[2], (other,))}):
                self.assertEqual(self.changed(before), {kind})

    def test_shared_footer_changes_every_kind(self):
        before = self.all()
        with patch.object(trial, 'PROMPT_FOOTER', trial.PROMPT_FOOTER + ' 추가'):
            self.assertEqual(self.changed(before), set(trial.KINDS))


class ResearchSignatureBridgeTests(unittest.TestCase):
    def test_research_fingerprint_ignores_other_kinds(self):
        from benefit_monitor.ai_review import fingerprint
        before = fingerprint(ROOT)
        row = wire_format.WIRES['festival']
        with patch.dict(wire_format.WIRES, {'festival': (row[0], lambda host: {'type': 'object'}, row[2], row[3])}), \
                patch.object(trial.KINDS['benefit'], 'task', '다른 지시'):
            self.assertEqual(fingerprint(ROOT), before)
        with patch.object(trial.KINDS['research'], 'task', '다른 지시'):
            self.assertNotEqual(fingerprint(ROOT), before)
        with patch.object(trial, 'PROMPT_FOOTER', '다른 꼬리말'):
            self.assertNotEqual(fingerprint(ROOT), before)

    def test_bridge_still_matches_the_current_research_contract(self):
        from benefit_monitor import ai_review
        self.assertEqual(ai_review.fingerprint(ROOT), ai_review.BRIDGED_FINGERPRINT,
                         '조사 계약(지침·꼬리말·작업 지시·스키마·복원 규칙)이 바뀌었다. 보류·거절 후보가 하루 한도 안에서 '
                         '다시 조사된다. 그 비용을 확인했다면 ai_review의 LEGACY/BRIDGED 상수와 이 검사를 함께 지운다.')

    def test_legacy_signature_is_equivalent_only_while_bridged(self):
        from benefit_monitor import ai_review
        legacy = ai_review._signature('cid', 'h1,h2', ai_review.LEGACY_FINGERPRINT + '\ninv')
        signature, same = ai_review._signatures('cid', 'h1,h2', ai_review.BRIDGED_FINGERPRINT, '\ninv')
        self.assertEqual(same, {signature, legacy})
        self.assertNotEqual(signature, legacy)
        signature, same = ai_review._signatures('cid', 'h1,h2', 'a-later-contract', '\ninv')
        self.assertEqual(same, {signature})


class VariantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        budget = TrialBudget.initialize(root/'budget.json', 'claude-haiku-5-5', '0.10', '0.50')
        self.client = trial.ClaudeClient(root, budget, 'fake-secret-for-tests')
        self.schema = wire_format.schema_for('festival', None)

    def test_baseline_request_body_is_unchanged(self):
        # Request IDs are hashes of the body: the regular request must stay byte-identical.
        expected = {'model': 'claude-haiku-5-5', 'max_tokens': 8192, 'system': 's', 'thinking': {'type': 'disabled'},
                    'messages': [{'role': 'user', 'content': 'u'}],
                    'output_config': {'format': {'type': 'json_schema', 'schema': self.schema}}}
        for payload in (self.client.payload('s', 'u', 8192, self.schema),
                        self.client.payload('s', 'u', 8192, self.schema, 'baseline')):
            self.assertEqual(json.dumps(payload), json.dumps(expected))
        self.assertEqual(self.client.payload('s', 'u'), {k: v for k, v in expected.items() if k != 'output_config'} | {'max_tokens': 4096})

    def test_measurement_variants_set_thinking_and_effort(self):
        for name, effort in (('adaptive-medium', 'medium'), ('adaptive-high', 'high')):
            payload = self.client.payload('s', 'u', 8192, self.schema, name)
            self.assertEqual(payload['thinking'], {'type': 'adaptive'})
            self.assertEqual(payload['output_config']['effort'], effort)
            self.assertEqual(payload['output_config']['format']['schema'], self.schema)
            self.assertEqual(payload['max_tokens'], 8192)
        with self.assertRaises(KeyError):
            self.client.payload('s', 'u', 8192, self.schema, 'adaptive-max')

    def test_answer_text_names_refusal_and_truncation(self):
        text = {'type': 'text', 'text': '{"a":1}'}
        thinking = {'type': 'thinking', 'thinking': '...'}
        self.assertEqual(trial.answer_text({'stop_reason': 'end_turn', 'content': [text]}), '{"a":1}')
        with self.assertRaisesRegex(ValueError, 'model refused'):
            trial.answer_text({'stop_reason': 'refusal', 'content': [text]})
        with self.assertRaisesRegex(ValueError, 'truncated at max_tokens'):
            trial.answer_text({'stop_reason': 'max_tokens', 'content': [text]})
        with self.assertRaisesRegex(ValueError, 'unexpected output'):
            trial.answer_text({'stop_reason': 'end_turn', 'content': [thinking, text]})
        with self.assertRaisesRegex(ValueError, 'unexpected output'):
            trial.answer_text({'stop_reason': 'tool_use', 'content': [text]}, 'adaptive-high')
        self.assertEqual(trial.answer_text({'stop_reason': 'end_turn', 'content': [thinking, text]}, 'adaptive-high'), '{"a":1}')


if __name__ == '__main__':
    unittest.main()
