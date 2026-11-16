import ast
import json
from pathlib import Path
import sys
import traceback

import pytest
pytest.importorskip("tornado", reason="Moonraker HTTP compatibility tests require Tornado")
import tornado.web
import tornado.testing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from moonraker_http_error_patch import candidate

SOURCE = (Path(__file__).parent / 'fixtures/moonraker_http_error_compat.py').read_text()


def handler(source):
    namespace = {'jsonw': json, 'traceback': traceback}
    exec(compile(source, 'reviewed-error-handler', 'exec'), namespace)
    return namespace['AuthorizedRequestHandler'].write_error


@pytest.mark.skipif(tornado.version_info >= (6, 5), reason="Factory HTTP reason handling requires Tornado 6.3.3; see README test command")
class TestHTTPErrorResponse(tornado.testing.AsyncHTTPTestCase):
    def runTest(self):
        pass  # Tornado 6.3 test adapter expects this on Python 3.12.
    def get_app(self):
        class Request(tornado.web.RequestHandler):
            write_error = handler(candidate(SOURCE))

            def get(self):
                code = int(self.get_argument('code', '400'))
                reason = self.get_argument('reason', 'ordinary refusal', strip=False)
                raise tornado.web.HTTPError(code, reason=reason)

        return tornado.web.Application([(r'/', Request)])

    def test_refusal_body_and_protocol_safe_status(self):
        from urllib.parse import urlencode
        for code, reason in [
                (400, 'ordinary refusal'),
                (400, 'CommandError: use physical HEAD\n'),
                (409, 'Filament changed\r\nX-Forged: injected'),
                (503, 'Printer unavailable\nWait for reconnect'),
                (400, '材料 unavailable')]:
            response = self.fetch('/?' + urlencode({'code': code, 'reason': reason}))
            assert response.code == code
            assert response.reason == tornado.httputil.responses[code]
            assert 'X-Forged' not in response.headers
            assert response.headers['Content-Type'].startswith('application/json')
            error = json.loads(response.body)['error']
            assert error['code'] == code and error['message'] == reason
            assert 'HTTPError' in error['traceback']


@pytest.mark.skipif(tornado.version_info >= (6, 5), reason="Factory HTTP reason handling requires Tornado 6.3.3; see README test command")
class TestOriginalHTTPError(tornado.testing.AsyncHTTPTestCase):
    def runTest(self):
        pass

    def get_app(self):
        class Request(tornado.web.RequestHandler):
            write_error = handler(SOURCE)

            def get(self):
                raise tornado.web.HTTPError(400, reason='CommandError: use physical HEAD\n')
        return tornado.web.Application([(r'/', Request)])

    def test_original_disconnects_instead_of_returning_refusal(self):
        from tornado.simple_httpclient import HTTPStreamClosedError
        with pytest.raises(HTTPStreamClosedError, match='Stream closed'):
            self.fetch('/')


def test_patch_is_exact_and_rejects_unknown_or_duplicate_handlers():
    for source in (SOURCE, SOURCE.replace('\n', '\r\n')):
        patched = candidate(source)
        ending = '\r\n' if '\r\n' in source else '\n'
        assert patched.replace('        self.set_status(status_code)' + ending, '', 1) == source
        ast.parse(patched)
        with pytest.raises(ValueError):
            candidate(patched)
    with pytest.raises(ValueError):
        candidate(SOURCE.replace("'message': self._reason", "'message': str(self._reason)"))
    with pytest.raises(ValueError):
        candidate(SOURCE + SOURCE)
