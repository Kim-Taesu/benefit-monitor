"""Prompt examples must pass the same code gates as real model output (2026-11-13).

A few-shot example that the gate rejects would teach the model to fail, so every <example>
in the grocery and health prompts is run through review() here."""
import json
import re
import unittest
from pathlib import Path

from benefit_monitor import benefit_pick, festival_pick, grocery_pick, health_notes, wire_format
from benefit_monitor.claude_trial import TASKS, input_from_message, system_prompt, user_message

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT/'docs/ai/prompts'


def examples(name, input_tag):
    text = (PROMPTS/name).read_text()
    rows = re.findall(r'<example>\s*<%s>\s*(.*?)\s*</%s>\s*<output>\s*(.*?)\s*</output>\s*</example>'
                      % (input_tag, input_tag), text, re.S)
    if not rows:
        raise AssertionError('no examples in ' + name)
    return rows


class PromptExampleTests(unittest.TestCase):
    def test_grocery_examples_pass_review(self):
        for raw_input, raw_output in examples('grocery-system.md', 'candidates'):
            candidates = json.loads(raw_input)
            draft = json.loads(raw_output)
            self.assertEqual(list(draft), list(wire_format.grocery_wire_schema(None)['properties'])[1:])
            names = [c['name'] for c in candidates]
            self.assertEqual(grocery_pick.review(draft, {'candidates': candidates}, names), [], draft['summary'])

    def test_health_examples_pass_review_in_schema_order(self):
        order = list(wire_format.health_wire_schema(None)['properties'])[1:]
        self.assertEqual(order, ['quotes', 'status', 'sentence'])
        for page, raw_output in examples('health-system.md', 'page_text'):
            draft = json.loads(raw_output)
            self.assertEqual(list(draft), order)
            self.assertEqual(health_notes.review(draft, {'page_text': page, 'district': '강남구'}), [], draft['sentence'])

    def test_festival_examples_pass_review(self):
        for raw_input, raw_output in examples('festival-system.md', 'candidates'):
            candidates = json.loads(raw_input)
            draft = json.loads(raw_output)
            self.assertEqual(list(draft), list(wire_format.festival_wire_schema(None)['properties'])[1:])
            names = [c['name'] for c in candidates]
            self.assertEqual(festival_pick.review(draft, {'candidates': candidates}, names), [], draft['summary'])

    def test_benefit_examples_pass_review(self):
        for raw_input, raw_output in examples('benefit-system.md', 'candidates'):
            candidates = json.loads(raw_input)
            draft = json.loads(raw_output)
            self.assertEqual(list(draft), list(wire_format.benefit_wire_schema(None)['properties'])[1:])
            self.assertEqual(benefit_pick.review(draft, {'candidates': candidates}), [], draft['summary'])


class PromptShapeTests(unittest.TestCase):
    def test_evidence_comes_before_verdict_in_wire_schemas(self):
        from benefit_monitor.verify_contract import wire_schema
        verify = wire_schema()['properties']
        claim = verify['claims']['items']['properties']
        self.assertLess(list(claim).index('segment_ids'), list(claim).index('verdict'))
        self.assertLess(list(verify).index('status_segment_ids'), list(verify).index('item_status'))
        fact = wire_format.research_wire_schema()['properties']['records']['items']['properties']['facts']['items']['properties']
        self.assertEqual(list(fact)[:2], ['field', 'segment_ids'])
        self.assertEqual(list(fact)[-1], 'status')

    def test_user_message_puts_data_first_and_task_last(self):
        data = {'candidates': [{'id': 'a', 'name': '배추'}]}
        for kind in TASKS:
            text = user_message(kind, data)
            self.assertTrue(text.startswith('<input>\n'))
            self.assertTrue(text.endswith(TASKS[kind]))
            self.assertEqual(input_from_message(text), data)

    def test_system_prompt_footer_is_current(self):
        for kind in TASKS:
            text = system_prompt(ROOT, kind)
            self.assertIn('<input>', text)
            self.assertNotIn('$5', text)
            self.assertNotIn('비공개 실험', text)


if __name__ == '__main__':
    unittest.main()
