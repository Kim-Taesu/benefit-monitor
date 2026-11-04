import unittest
from datetime import datetime

from benefit_monitor import publish

NOW = datetime.fromisoformat('2026-11-04T10:00:00+09:00')


def item(**kw):
    base = dict(deadline_at=None, valid_from=None, valid_until=None, validity_kind='fixed')
    base.update(kw)
    return base


class PageTimingTests(unittest.TestCase):
    def test_deadline_today_and_soon(self):
        info = publish.timing(item(deadline_at='2026-11-04T23:59:00+09:00', valid_until='2026-11-04'), NOW)
        self.assertEqual(info['badge'], '오늘 신청 마감')
        self.assertIn('종료일은 공식 안내에서 확인', info['period'])
        info = publish.timing(item(deadline_at='2026-11-07T18:00:00+09:00', valid_from='2026-11-10', valid_until='2026-11-24'), NOW)
        self.assertEqual(info['badge'], '신청 마감 D-3')
        self.assertIn('신청 마감: 2026.11.07 18:00 (KST) (D-3)', info['apply'])
        self.assertIn('2026.11.10 ~ 2026.11.24', info['period'])

    def test_period_ongoing_and_future(self):
        self.assertEqual(publish.timing(item(valid_until='2026-11-04'), NOW)['badge'], '오늘 종료')
        self.assertEqual(publish.timing(item(valid_until='2026-12-31'), NOW)['badge'], '진행 중')
        ongoing = publish.timing(item(validity_kind='ongoing'), NOW)
        self.assertEqual((ongoing['badge'], ongoing['period'], ongoing['days']), ('상시 운영', '기간: 상시 운영', None))
        future = publish.timing(item(valid_from='2026-11-09', valid_until='2026-12-05'), NOW)
        self.assertEqual((future['badge'], future['days']), ('시작 전 D-5', None))


if __name__ == '__main__':
    unittest.main()
