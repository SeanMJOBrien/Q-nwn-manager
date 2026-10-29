"""Local web server for tfn-studio: JSON API + static pages (stdlib only).

Security model (the editor has no login, like Q-nwn-manager's web editor):
  * binds to 127.0.0.1 by default and rejects requests whose Host header is not one we serve;
  * every state-changing request (POST/DELETE) must carry the per-run token in `X-Studio-Token`
    (fetched from GET /api/session, same-origin only - no CORS headers are ever sent) and, when an
    Origin header is present, it must match the Host;
  * file writes only happen through change sets confined to <TFN>/src (see changeset.py).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import re
import secrets
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import index as IX
from . import mdhtml
from . import prefabs as PF
from . import quests as QS
from . import spawns as SP
from .project import STUDIO_ROOT, NotFoundError, ProjectError
from .service import SPEC_KINDS, Studio

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 8 * 1024 * 1024
PAGES = {"/": "index.html", "/camps": "camps.html", "/spawns": "spawns.html", "/quests": "quests.html",
         "/changes": "changes.html"}
# The manual is one self-contained file in the project root (MANUAL.html) that also opens straight from the file system;
# the studio serves it here. The plain-text docs are what the manual links to (fixed whitelist, read-only).
MANUAL_PATHS = ("/manual", "/manual/", "/MANUAL.html")
TEXT_DOCS = {"/README.md": "README.md", "/PLAN.md": "PLAN.md", "/MANUAL.md": "MANUAL.md"}
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Request:
    def __init__(self, method: str, path: str, query: dict[str, str], params: tuple, body: bytes):
        self.method, self.path, self.query, self.params, self._body = method, path, query, params, body

    def json(self) -> Any:
        if not self._body:
            return {}
        try:
            return json.loads(self._body.decode("utf-8"))
        except ValueError:
            raise ApiError(400, "request body is not valid JSON")


Handler = Callable[[Request], Any]


class App:
    def __init__(self, studio: Studio, host: str, port: int):
        self.studio = studio
        self.token = secrets.token_urlsafe(24)
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        self.doc_root = STUDIO_ROOT      # where MANUAL.html and the plain-text docs live (tests point it elsewhere)
        if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0", ""):
            self.allowed_hosts.add(f"{host}:{port}")
        self.op_lock = threading.Lock()  # serialise staging/apply (they write files)
        self.routes: list[tuple[str, re.Pattern, Handler]] = []
        self._register()

    # ----------------------------------------------------------- routing
    def route(self, method: str, pattern: str):
        def deco(fn: Handler) -> Handler:
            self.routes.append((method, re.compile("^" + pattern + "$"), fn))
            return fn
        return deco

    def dispatch(self, method: str, path: str, query: dict, body: bytes) -> tuple[int, Any]:
        for m, rx, fn in self.routes:
            if m != method:
                continue
            match = rx.match(path)
            if match:
                try:
                    return 200, fn(Request(method, path, query, match.groups(), body))
                except ApiError as e:
                    return e.status, {"error": e.message}
                except NotFoundError as e:
                    return 404, {"error": str(e)}
                except ProjectError as e:
                    return 400, {"error": str(e)}
                except FileNotFoundError as e:
                    return 404, {"error": f"not found: {e.filename or e}"}
                except Exception as e:  # keep the server alive; details go to the console only
                    traceback.print_exc()
                    return 500, {"error": f"internal error: {type(e).__name__}: {e}"}
        return 404, {"error": "no such endpoint"}

    # --------------------------------------------------------- endpoints
    def _register(self) -> None:
        r, st = self.route, self.studio

        @r("GET", "/api/session")
        def session(req):
            pr = st.project
            generic = pr.profile == "generic"
            return {"token": self.token, "tfn_root": str(pr.root), "branch": pr.git_branch(),
                    "profile": pr.profile, "layout": pr.layout,
                    # what this kind of module can use: the camp/spawn engine and TFN's numbered quest scripts are TFN's own
                    "features": {"spawns": not generic, "random_camps": not generic, "legacy_quest_scripts": not generic},
                    "brand": "Content Studio" if generic else "TFN Content Studio"}

        @r("GET", "/api/status")
        def status(req):
            return st.status()

        @r("POST", "/api/index/refresh")
        def index_refresh(req):
            st.refresh_background()
            return {"ok": True}

        @r("GET", "/api/areas")
        def areas(req):
            keep = ("resref", "name", "width", "height", "cr", "interior", "underground", "natural", "tileset",
                    "groups", "counts", "plans", "markers", "hooks", "error")
            return [{k: a.get(k) for k in keep} for a in sorted(st.areas.values(), key=lambda a: a["resref"])]

        @r("GET", r"/api/areas/([A-Za-z0-9_]{1,32})")
        def area(req):
            return st.area_detail(req.params[0])

        @r("GET", r"/api/areas/([A-Za-z0-9_]{1,32})/walk")
        def area_walk(req):
            return st.walk_grid(req.params[0])

        @r("GET", "/api/palette/placeables")
        def placeables(req):
            return st.palette()

        @r("GET", "/api/palette/creatures")
        def creatures(req):
            keep = ("resref", "name", "cr", "kind", "faction", "race", "appearance", "gender", "conversation",
                    "plot", "boss", "classes", "script_death")
            tfn = [{k: c.get(k) for k in keep} for c in sorted(st.creatures.values(), key=lambda c: c["resref"])]
            if req.query.get("base") == "1":
                tfn += IX.base_creature_palette(st.areas, st.creatures)
            return tfn

        @r("GET", "/api/items")
        def items(req):
            return [{k: i.get(k) for k in ("resref", "name", "tag", "base_item", "cost", "plot")}
                    for i in sorted(st.items.values(), key=lambda i: i["resref"])]

        @r("GET", "/api/utes")
        def utes(req):
            usage = {}
            for a in st.areas.values():
                for g in a.get("groups") or []:
                    usage[g["ute"]] = usage.get(g["ute"], 0) + 1
            return [dict(u, used_by=usage.get(u["resref"], 0)) for u in sorted(st.utes.values(), key=lambda u: u["resref"])]

        @r("GET", r"/api/utes/([A-Za-z0-9_]{1,32})")
        def ute_get(req):
            res = req.params[0]
            ute = st.project.read("ute", res)
            desc = SP.describe_ute(ute)
            return {"describe": desc, "usage": SP.usage(st.areas, res), "mix": SP.expected_mix(desc, 10),
                    "spec": {"resref": res, "name": st.utes.get(res, {}).get("name", res),
                             "difficulty": desc["difficulty"], "rare": desc["rare"],
                             "creatures": [dict(resref=c["resref"], unique=False) for c in desc["commons"]]
                                          + [dict(resref=c["resref"], unique=True) for c in desc["uniques"]]}}

        @r("POST", "/api/utes/preview")
        def ute_preview(req):
            body = req.json()
            spec = body.get("spec") or {}
            existing = st.project.read("ute", spec["resref"]) if spec.get("resref") and st.project.exists("ute", spec["resref"]) else None
            ute, warns = SP.build_ute(st.project, spec, existing)
            desc = SP.describe_ute(ute)
            area_cr = None
            if body.get("area") and body["area"] in st.areas:
                area_cr = st.areas[body["area"]].get("cr")
            return {"describe": desc, "mix": SP.expected_mix(desc, int(body.get("spawns") or 10)),
                    "warnings": warns, "cr_notes": SP.cr_check(desc, area_cr)}

        @r("POST", "/api/utes/stage")
        def ute_stage(req):
            with self.op_lock:
                return st.stage_ute(req.json().get("spec") or {}).to_dict()

        @r("GET", "/api/prefabs")
        def prefabs(req):
            return list(st.prefabs().values())

        @r("POST", "/api/prefabs")
        def prefab_save(req):
            return {"ok": True, "file": st.save_prefab(req.json().get("prefab") or {})}

        @r("POST", "/api/camps/stage")
        def camp_stage(req):
            with self.op_lock:
                return st.stage_camp(req.json().get("plan") or {}).to_dict()

        @r("POST", "/api/camps/event-info")
        def camp_event_info(req):
            return st.camp_event_info(req.json().get("plan") or {})

        @r("POST", "/api/camps/suggest-spots")
        def camp_suggest_spots(req):
            body = req.json()
            try:
                count = int(body.get("count") or 6)
            except (TypeError, ValueError):
                raise ApiError(400, "count must be a whole number")
            return st.suggest_camp_spots(body.get("plan") or {}, count, str(body.get("seed") or ""))

        @r("GET", r"/api/specs/(camps|quests|utes)")
        def specs_list(req):
            return st.list_specs(req.params[0])

        @r("GET", r"/api/specs/(camps|quests|utes)/([a-z0-9_]{1,40})")
        def specs_get(req):
            return st.load_spec(req.params[0], req.params[1])

        @r("POST", r"/api/specs/(camps|quests|utes)")
        def specs_save(req):
            return {"ok": True, "id": st.save_spec(req.params[0], req.json().get("spec") or {})}

        @r("DELETE", r"/api/specs/(camps|quests|utes)/([a-z0-9_]{1,40})")
        def specs_delete(req):
            return {"ok": st.delete_spec(req.params[0], req.params[1])}

        @r("POST", "/api/quests/describe")
        def quest_describe(req):
            return {"stages": QS.describe(req.json().get("spec") or {})}

        @r("POST", "/api/quests/stage")
        def quest_stage(req):
            with self.op_lock:
                return st.stage_quest(req.json().get("spec") or {}).to_dict()

        @r("GET", "/api/journal")
        def journal(req):
            wiring = st.quest_wiring()
            return [dict(q, wiring=wiring.get(q["tag"], [])) for q in st.journal()]

        @r("GET", "/api/changes")
        def changes(req):
            return st.status()["changes"]

        @r("GET", r"/api/changes/([0-9a-z-]{3,80})")
        def change_get(req):
            return st.load_change(req.params[0]).summary()

        @r("GET", r"/api/changes/([0-9a-z-]{3,80})/diff")
        def change_diff(req):
            cs = st.load_change(req.params[0])
            rel = req.query.get("file")
            if rel and rel not in cs.files:
                raise ApiError(404, "no such file in change set")
            text = cs.diff(rel)
            limit = 400_000
            return {"diff": text[:limit], "truncated": len(text) > limit, "size": len(text)}

        @r("POST", r"/api/changes/([0-9a-z-]{3,80})/validate")
        def change_validate(req):
            with self.op_lock:
                return {"issues": [i.to_dict() for i in st.validate_change(req.params[0])]}

        @r("POST", r"/api/changes/([0-9a-z-]{3,80})/apply")
        def change_apply(req):
            body = req.json()
            with self.op_lock:
                return st.apply_change(req.params[0], allow_dirty=bool(body.get("allow_dirty")),
                                       force=bool(body.get("force")))

        @r("POST", r"/api/changes/([0-9a-z-]{3,80})/undo")
        def change_undo(req):
            with self.op_lock:
                return st.undo_change(req.params[0], force=bool(req.json().get("force")))

        @r("POST", r"/api/changes/([0-9a-z-]{3,80})/discard")
        def change_discard(req):
            with self.op_lock:
                return {"ok": st.discard_change(req.params[0])}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "tfn-studio"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # quiet; errors are printed by dispatch
            pass

        # -------------------------------------------------------- helpers
        def _host_ok(self) -> bool:
            return (self.headers.get("Host") or "") in app.allowed_hosts

        def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None, csp: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             csp or "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                    "frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _static(self, rel: str) -> None:
            p = (WEB_DIR / rel).resolve()
            try:
                p.relative_to(WEB_DIR.resolve())
            except ValueError:
                return self._json(404, {"error": "not found"})
            if not p.is_file():
                return self._json(404, {"error": "not found"})
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json",):
                ctype += "; charset=utf-8"
            self._send(200, p.read_bytes(), ctype)

        def _manual(self) -> None:
            """MANUAL.html as it is on disk (generated from MANUAL.md by scripts/build_manual.py); rendered on the fly if missing."""
            html_file, md_file = app.doc_root / "MANUAL.html", app.doc_root / "MANUAL.md"
            if html_file.is_file():
                page = html_file.read_text(encoding="utf-8")
            elif md_file.is_file():
                page = mdhtml.render_page(md_file.read_text(encoding="utf-8"))
            else:
                return self._json(404, {"error": "MANUAL.html not found"})
            # the page carries one inline script (copy buttons, contents highlighting): allow exactly that script by hash
            digests = [base64.b64encode(hashlib.sha256(src.encode("utf-8")).digest()).decode()
                       for src in re.findall(r"<script>(.*?)</script>", page, re.S)]
            script_src = "script-src " + " ".join(f"'sha256-{d}'" for d in digests) + "; " if digests else ""
            csp = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                   + script_src + "frame-ancestors 'none'")
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", csp=csp)

        def _text_doc(self, name: str) -> None:
            p = app.doc_root / name
            if not p.is_file():
                return self._json(404, {"error": "not found"})
            self._send(200, p.read_bytes(), "text/plain; charset=utf-8")

        def _handle(self, method: str) -> None:
            if not self._host_ok():
                return self._json(403, {"error": "bad Host header"})
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            if method == "GET" and not path.startswith("/api/"):
                if path in PAGES:
                    return self._static(PAGES[path])
                if path in MANUAL_PATHS:
                    return self._manual()
                if path in TEXT_DOCS:
                    return self._text_doc(TEXT_DOCS[path])
                if path.startswith("/static/"):
                    return self._static(path[1:])
                return self._json(404, {"error": "not found"})
            if method != "GET":
                origin = self.headers.get("Origin")
                if origin and origin != f"http://{self.headers.get('Host')}":
                    return self._json(403, {"error": "cross-origin request refused"})
                tok = self.headers.get("X-Studio-Token") or ""
                if not hmac.compare_digest(tok.encode(), app.token.encode()):
                    return self._json(403, {"error": "missing or wrong X-Studio-Token"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            body = self.rfile.read(length) if length else b""
            status, payload = app.dispatch(method, path, query, body)
            self._json(status, payload)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_DELETE(self):
            self._handle("DELETE")

    return H


def serve(studio: Studio, host: str = "127.0.0.1", port: int = 8350, open_browser: bool = False) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: binding to {host!r}; this tool has no login. Keep it on 127.0.0.1 or put it behind an "
              "authenticated reverse proxy.", file=sys.stderr)
    app = App(studio, host, port)
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(app))
    except OSError as exc:
        raise ProjectError(f"cannot listen on {host}:{port} ({exc.strerror or exc}). Is another studio already running? "
                           f"Stop it (Ctrl+C in its terminal) or use  --port {port + 1}")
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"tfn-studio serving {studio.project.root} at {url}  (Ctrl+C to stop)", flush=True)
    studio.refresh_background()  # warm the indexes without blocking startup
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def make_test_server(studio: Studio, port: int = 0):
    """Server on an ephemeral port for tests; returns (httpd, app, thread)."""
    app = App(studio, "127.0.0.1", port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    app.allowed_hosts.add(f"127.0.0.1:{httpd.server_address[1]}")
    app.allowed_hosts.add(f"localhost:{httpd.server_address[1]}")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, app, t
