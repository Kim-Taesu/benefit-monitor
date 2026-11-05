import json
from pathlib import Path
import tempfile
import unittest

from benefit_monitor.quality_baseline import classify, evaluation_set

ROOT = Path(__file__).resolve().parents[1]


def doc(url, body):
    return dict(id='doc', source_id='culture', final_url=url, requested_url=url, fetch_status='ok', body=body,
                retrieved_at='2026-11-05T12:00:00+09:00')


class QualityBaselineTests(unittest.TestCase):
    def test_reasons_map_to_one_category(self):
        cases = {'unknown requires null value and no evidence': 'format',
                 "Invalid isoformat string: '2026-11-02T00:00:00+09:00'": 'format',
                 "'2a1890832ea799485dff0ed2'": 'format',
                 'quote not in successful source': 'grounding',
                 'proposed field contradicts supported claim': 'semantic',
                 'required fields or restriction coverage requires review': 'semantic',
                 'topic semantics requires review': 'semantic',
                 'invalid_or_truncated_model_output': 'transport',
                 'something new': 'unclassified'}
        for reason, category in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(classify(reason), category)

    def test_holdout_excludes_sent_bodies_and_their_url_variants(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            run = root/'.tools/claude-trial/live/runs/r1'
            run.mkdir(parents=True)
            sent = dict(synthetic=False, documents=[doc('https://yeyak.seoul.go.kr/a', '보낸 원문')])
            (run/'input.json').write_text(json.dumps(sent))
            other = root/'.tools/inputs'
            other.mkdir(parents=True)
            (other/'x.json').write_text(json.dumps(dict(synthetic=False, documents=[
                doc('https://yeyak.seoul.go.kr/a', '보낸 원문'), doc('https://yeyak.seoul.go.kr/a', '같은 URL 새 버전'),
                doc('https://yeyak.seoul.go.kr/b', '처음 보는 원문')])))
            (other/'fixture.json').write_text(json.dumps(dict(synthetic=True, documents=[doc('https://x.example/c', '합성')])))
            manifest = evaluation_set(root)
        self.assertEqual(manifest['counts'], {'dev': 1, 'holdout': 1, 'excluded_dev_variant': 1})
        holdout = [r for r in manifest['documents'] if r['split'] == 'holdout']
        self.assertEqual(holdout[0]['url'], 'https://yeyak.seoul.go.kr/b')
        self.assertNotIn('body', json.dumps(manifest, ensure_ascii=False).replace('body_sha256', ''))


if __name__ == '__main__':
    unittest.main()
