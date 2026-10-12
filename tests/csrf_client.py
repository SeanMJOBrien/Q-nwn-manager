"""Tiny HTTP client for the console's HTTP round-trip tests: keeps the session
cookie and adds the CSRF token + render time the console's forms carry, the
way a browser submitting one of its pages would."""
import http.cookiejar
import re
import time
import urllib.parse
import urllib.request


class Client:
    def __init__(self, port, warm_path="/areas"):
        self.base = "http://127.0.0.1:%d" % port
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.warm_path = warm_path
        self.token = None

    def get(self, path, timeout=5):
        html = self.opener.open(self.base + path, timeout=timeout).read().decode()
        m = re.search(r"name='_csrf' value='([0-9a-f]+)'", html)
        if m:
            self.token = m.group(1)
        return html

    def post(self, path, data, timeout=5, rendered=None, token=True):
        if token and self.token is None:
            self.get(self.warm_path)
        data = dict(data)
        if token:
            data["_csrf"] = self.token
            # default: "the page was rendered an instant ago"; a stale-form
            # test passes an older time explicitly
            data["_rendered"] = "%.6f" % (time.time() if rendered is None
                                          else rendered)
        body = urllib.parse.urlencode(data, doseq=True).encode()
        return self.opener.open(self.base + path, data=body,
                                timeout=timeout).read().decode()
