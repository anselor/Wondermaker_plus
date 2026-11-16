# SPDX-License-Identifier: GPL-3.0-or-later
# Reviewed AuthorizedRequestHandler.write_error from WM 1.1.13 Moonraker.
class AuthorizedRequestHandler:
    def write_error(self, status_code: int, **kwargs) -> None:
        err = {'code': status_code, 'message': self._reason}
        if 'exc_info' in kwargs:
            err['traceback'] = "\n".join(
                traceback.format_exception(*kwargs['exc_info']))
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(jsonw.dumps({'error': err}))
