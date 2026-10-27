import socket
import ssl
import unittest
from datetime import timedelta
from urllib.error import URLError,HTTPError
from benefit_monitor import operations
from test_pipeline import NOW

class DiagnosticTests(unittest.TestCase):
    def test_nested_errors_have_safe_distinct_categories(self):
        cases=[(URLError(socket.gaierror(-2,'private host')),'dns'),
               (URLError(ssl.SSLError('private detail')),'tls'),
               (URLError(TimeoutError('private URL')),'timeout'),
               (HTTPError('https://private/',403,'secret',None,None),'http_403'),
               (ValueError('robots disallows page'),'robots_denied'),
               (RuntimeError('Public HTTP request budget exhausted'),'request_budget')]
        for error,expected in cases:
            result=operations.error_info(error)
            self.assertEqual(result['category'],expected)
            self.assertNotIn('private',str(result));self.assertNotIn('secret',str(result))

    def test_consecutive_failures_survive_then_reset_on_success(self):
        state={}
        operations.health(state,[],[dict(source='test',category='tls')],NOW)
        operations.health(state,[],[dict(source='test',category='tls')],NOW+timedelta(days=1))
        self.assertEqual(state['sources']['test']['consecutive_failures'],2)
        operations.health(state,['test'],[],NOW+timedelta(days=2))
        row=state['sources']['test']
        self.assertEqual(row['consecutive_failures'],0)
        self.assertEqual(row['last_success_at'],(NOW+timedelta(days=2)).isoformat())
