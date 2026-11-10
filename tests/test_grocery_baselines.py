import copy
import json
import unittest
from collections import Counter
from pathlib import Path

from benefit_monitor import grocery_baselines

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests' / 'fixtures' / 'grocery_baselines'


def repo_source():
    return json.loads((ROOT / 'sources' / 'groceries.json').read_text(encoding='utf-8'))['collect']


class BasketTests(unittest.TestCase):
    def test_basket_accepts_repo_config(self):
        items = grocery_baselines.basket(repo_source())
        self.assertEqual(len(items), 25)
        groups = Counter(i['group'] for i in items)
        self.assertEqual((groups['고기·알'], groups['채소'], groups['기타']), (7, 12, 6))
        for item in items:
            self.assertEqual(len({'kamis', 'ekape'} & item.keys()), 1)

    def test_basket_required_aliases(self):
        by_id = {i['id']: i for i in grocery_baselines.basket(repo_source())}
        self.assertTrue({'계란', '달걀'} <= set(by_id['egg_tray']['aliases']))
        self.assertTrue({'대파', '파'} <= set(by_id['green_onion']['aliases']))
        self.assertTrue({'애호박', '호박'} <= set(by_id['zucchini']['aliases']))
        self.assertTrue({'오징어', '물오징어'} <= set(by_id['squid']['aliases']))
        self.assertTrue({'한우', '등심', '소고기'} <= set(by_id['hanwoo_sirloin']['aliases']))
        self.assertTrue({'갈비살', '소갈비살'} <= set(by_id['us_short_rib']['aliases']))
        self.assertTrue({'닭', '생닭', '닭고기'} <= set(by_id['chicken']['aliases']))

    def test_basket_rejects_duplicate_id(self):
        source = copy.deepcopy(repo_source())
        source['basket'][1]['id'] = source['basket'][0]['id']
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_both_kamis_and_ekape(self):
        source = copy.deepcopy(repo_source())
        source['basket'][0]['kamis'] = copy.deepcopy(source['basket'][-1]['kamis'])
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_26_items(self):
        source = copy.deepcopy(repo_source())
        extra = copy.deepcopy(source['basket'][0])
        extra['id'] = 'extra_item'
        source['basket'].append(extra)
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_bad_fields(self):
        for mutate in (lambda i: i.update(id='Bad1'), lambda i: i.update(aliases=[]),
                       lambda i: i.update(aliases=['a'] * 6), lambda i: i.update(group='과일'),
                       lambda i: i['row'].update(kind='fish'), lambda i: i.update(extra=1)):
            source = copy.deepcopy(repo_source())
            mutate(source['basket'][0])
            with self.assertRaises(ValueError):
                grocery_baselines.basket(source)

    def test_basket_rows_exist_in_fixture_bundle(self):
        ids = set(json.loads((FIXTURES / 'row_ids.json').read_text(encoding='utf-8')))
        for item in grocery_baselines.basket(repo_source()):
            self.assertIn(item['row']['id'], ids)

    def test_meat_row_matches_ekape_code_and_label(self):
        for item in grocery_baselines.basket(repo_source()):
            if 'ekape' in item:
                e = item['ekape']
                self.assertEqual(item['row'], {'kind': 'meat', 'id': '%s-%s-%s' % (e['species'], e['part'], e['label'])})
            else:
                self.assertEqual(item['row']['kind'], 'produce')


if __name__ == '__main__':
    unittest.main()
