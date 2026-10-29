"""Web API tests against an in-process server on an ephemeral port (mini TFN, never the real tree)."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.fixture import MiniTfnCase  # noqa: F401  (sets sys.path)
from tests.test_camps import PLAN
from tests.test_campevent import PLAN as EVENT_PLAN
from tests.test_quests import SPEC

from tfnstudio.server import make_test_server
from tfnstudio.service import Studio


class ServerTests(MiniTfnCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shutil
        from tfnstudio import prefabs as PF
        shutil.copytree(PF.PREFAB_DIR, Path(cls.tmp.name) / "prefabs")
        cls.studio = Studio(cls.root, Path(cls.tmp.name) / "studio", spec_root=Path(cls.tmp.name) / "specs",
                            prefab_dir=Path(cls.tmp.name) / "prefabs")
        cls.httpd, cls.app, cls.thread = make_test_server(cls.studio)
        cls.port = cls.httpd.server_address[1]
        cls.token = cls.app.token

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        super().tearDownClass()

    # --------------------------------------------------------------- helpers
    def call(self, method, path, body=None, token=True, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h["X-Studio-Token"] = self.token
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw
        return resp.status, data

    # ------------------------------------------------------------- security
    def test_session_and_host_check(self):
        status, data = self.call("GET", "/api/session", token=False)
        self.assertEqual(status, 200)
        self.assertEqual(data["token"], self.token)
        status, _ = self.call("GET", "/api/session", token=False, host="evil.example:80")
        self.assertEqual(status, 403)

    def test_post_requires_token_and_same_origin(self):
        status, _ = self.call("POST", "/api/camps/stage", {"plan": PLAN}, token=False)
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/camps/stage", {"plan": PLAN},
                              headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        status, _ = self.call("POST", "/api/camps/stage", {"plan": PLAN}, headers={"X-Studio-Token": "wrong"})
        self.assertEqual(status, 403)

    def test_pages_and_security_headers(self):
        for path in ("/", "/camps", "/spawns", "/quests", "/changes"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
            resp = conn.getresponse()
            body = resp.read().decode()
            self.assertEqual(resp.status, 200, path)
            self.assertIn('<main id="app">', body, path)
            self.assertIn("text/html", resp.getheader("Content-Type"))
            self.assertIn("default-src 'self'", resp.getheader("Content-Security-Policy"))
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.getheader("Cache-Control"), "no-store")
            self.assertIsNone(resp.getheader("Access-Control-Allow-Origin"))
            conn.close()
        for js in ("common.js", "areamap.js", "camps.js", "quests.js", "spawns.js", "uteeditor.js", "changes.js", "dashboard.js"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            conn.request("GET", f"/static/{js}", headers={"Host": f"127.0.0.1:{self.port}"})
            resp = conn.getresponse()
            resp.read()
            self.assertEqual(resp.status, 200, js)
            self.assertIn("javascript", resp.getheader("Content-Type"), js)
            conn.close()
        self.assertEqual(self.call("GET", "/nope", token=False)[0], 404)

    # ----------------------------------------------------------------- manual
    def raw_get(self, path, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        data = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, headers, data

    def test_manual_is_served_from_the_project_root_with_a_script_hash_policy(self):
        from tests.fixture import ROOT
        disk = (ROOT / "MANUAL.html").read_bytes()
        for path in ("/manual", "/manual/", "/MANUAL.html"):
            status, headers, data = self.raw_get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(data, disk, path)
            self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertNotIn("access-control-allow-origin", headers)
        directives = {d.strip().split(" ", 1)[0]: d.strip().split(" ", 1)[1] for d in headers["content-security-policy"].split(";") if " " in d.strip()}
        self.assertEqual(directives["default-src"], "'self'")
        self.assertEqual(directives["frame-ancestors"], "'none'")
        script = re.search(r"<script>(.*?)</script>", disk.decode("utf-8"), re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        self.assertEqual(directives["script-src"], f"'sha256-{digest}'")           # exactly the inline script, nothing else
        # every other page keeps the strict policy (no inline script allowed at all)
        _, other, _ = self.raw_get("/")
        self.assertNotIn("script-src", other["content-security-policy"])

    def test_manual_still_requires_a_known_host(self):
        self.assertEqual(self.raw_get("/manual", host="evil.example:80")[0], 403)
        self.assertEqual(self.raw_get("/README.md", host="evil.example:80")[0], 403)

    def test_plain_text_docs_are_a_fixed_whitelist(self):
        from tests.fixture import ROOT
        for name in ("README.md", "PLAN.md", "MANUAL.md"):
            status, headers, data = self.raw_get("/" + name)
            self.assertEqual(status, 200, name)
            self.assertEqual(headers["content-type"], "text/plain; charset=utf-8")
            self.assertEqual(data, (ROOT / name).read_bytes(), name)
        for path in ("/CLAUDE.md", "/PROGRESS.md", "/bin/tfn-studio", "/tfnstudio/server.py", "/MANUAL.md/", "/%2e%2e/README.md",
                     "/manual/../CLAUDE.md", "/README.md%00.txt", "/specs/quests/q_example_wolves.json"):
            self.assertEqual(self.raw_get(path)[0], 404, path)

    def test_manual_is_rendered_from_the_markdown_when_the_html_file_is_missing(self):
        old = self.app.doc_root
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.app.doc_root = root
            try:
                self.assertEqual(self.raw_get("/manual")[0], 404)                            # neither file exists
                (root / "MANUAL.md").write_text("# Hello\n\nsome `text`\n", encoding="utf-8")
                status, headers, data = self.raw_get("/manual")
                self.assertEqual(status, 200)
                self.assertIn(b'<h1 id="hello">Hello</h1>', data)
                self.assertIn("script-src 'sha256-", headers["content-security-policy"])
                (root / "MANUAL.html").write_text("<!doctype html><title>on disk</title>", encoding="utf-8")
                status, headers, data = self.raw_get("/manual")
                self.assertIn(b"on disk", data)                                              # the generated file wins when present
                self.assertNotIn("script-src", headers["content-security-policy"])           # no inline script, so none is allowed
            finally:
                self.app.doc_root = old

    def test_static_path_traversal_blocked(self):
        for path in ("/static/../server.py", "/static/%2e%2e/server.py", "/../etc/passwd"):
            status, _ = self.call("GET", path, token=False)
            self.assertEqual(status, 404, path)

    # ------------------------------------------------------------------ reads
    def test_reads(self):
        status, areas = self.call("GET", "/api/areas")
        self.assertEqual(status, 200)
        self.assertEqual({a["resref"] for a in areas}, {"bandit_cave", "goblin2"})
        self.assertNotIn("pl", areas[0])
        status, area = self.call("GET", "/api/areas/bandit_cave")
        self.assertEqual(status, 200)
        self.assertEqual(len(area["tiles"]), 64)
        self.assertTrue(any(o["resref"] == "random1" for o in area["objects"]))
        status, pal = self.call("GET", "/api/palette/placeables")
        self.assertTrue(any(p["resref"] == "plc_bedrolls" for p in pal))
        status, cre = self.call("GET", "/api/palette/creatures")
        self.assertTrue(any(c["resref"] == "bandit" and c["kind"] == "other" for c in cre))
        status, base = self.call("GET", "/api/palette/creatures?base=1")
        self.assertTrue(any(c["kind"] == "base" and c["resref"] == "goblin_shaman" for c in base))
        self.assertFalse(any(c["kind"] == "base" for c in cre))            # opt-in only
        status, items = self.call("GET", "/api/items")
        self.assertTrue(any(i["resref"] == "q_brain" for i in items))
        status, utes = self.call("GET", "/api/utes")
        self.assertEqual(utes[0]["resref"], "bandit_moderate")
        status, one = self.call("GET", "/api/utes/bandit_moderate")
        self.assertEqual(one["describe"]["unique_chance"], 20)
        status, pf = self.call("GET", "/api/prefabs")
        self.assertGreaterEqual(len(pf), 8)
        status, jr = self.call("GET", "/api/journal")
        self.assertGreater(len(jr), 50)
        self.assertEqual(self.call("GET", "/api/areas/no_such_area")[0], 404)
        self.assertEqual(self.call("GET", "/api/areas/..%2f..%2fetc")[0], 404)

    def test_ute_preview(self):
        status, data = self.call("POST", "/api/utes/preview", {
            "spec": {"resref": "zz_prev", "difficulty": 4, "creatures": [{"resref": "bandit"}, {"resref": "bandit_mage", "unique": True}]},
            "spawns": 12, "area": "bandit_cave"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["describe"]["unique_chance"], 25)
        self.assertGreater(data["mix"]["expected_total"], 12)
        status, data = self.call("POST", "/api/utes/preview", {"spec": {"resref": "Bad Name", "creatures": [{"resref": "bandit"}]}})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # ------------------------------------------------------- stage/apply flow
    def test_camp_stage_diff_validate_apply_undo(self):
        status, res = self.call("POST", "/api/camps/stage", {"plan": PLAN})
        self.assertEqual(status, 200, res)
        self.assertTrue(res["ok"], res["issues"])
        cid = res["id"]
        status, summary = self.call("GET", f"/api/changes/{cid}")
        self.assertEqual({f["rel"] for f in summary["files"]}, {"src/git/bandit_cave.git.json", "src/ute/unit_grp.ute.json"})
        status, diff = self.call("GET", f"/api/changes/{cid}/diff?file=src/ute/unit_grp.ute.json")
        self.assertIn("unit_grp", diff["diff"])
        self.assertEqual(self.call("GET", f"/api/changes/{cid}/diff?file=src/evil.json")[0], 404)
        status, val = self.call("POST", f"/api/changes/{cid}/validate", {})
        self.assertFalse([i for i in val["issues"] if i["level"] == "error"])
        status, applied = self.call("POST", f"/api/changes/{cid}/apply", {})
        self.assertTrue(applied["ok"], applied)
        self.assertTrue((self.root / "src/ute/unit_grp.ute.json").is_file())
        status, listing = self.call("GET", "/api/changes")
        self.assertTrue(next(c for c in listing if c["id"] == cid)["applied"])
        status, undone = self.call("POST", f"/api/changes/{cid}/undo", {})
        self.assertTrue(undone["ok"], undone)
        self.assertFalse((self.root / "src/ute/unit_grp.ute.json").exists())
        self.assertTrue(self.call("POST", f"/api/changes/{cid}/discard", {})[1]["ok"])

    def test_random_camp_preview_stage_apply_undo(self):
        plan = json.loads(json.dumps(EVENT_PLAN))
        plan["camp_event"]["replaces_group"] = 1
        status, info = self.call("POST", "/api/camps/event-info", {"plan": plan})
        self.assertEqual(status, 200, info)
        self.assertEqual(len(info["variants"]), 3)
        self.assertEqual(info["script"], "eve_wolf_den")
        self.assertAlmostEqual(info["wiring"]["effective"], 0.2)
        self.assertEqual(info["errors"], [])
        self.assertFalse((self.root / "src/nss/eve_wolf_den.nss").exists())          # a preview writes nothing
        status, off = self.call("POST", "/api/camps/event-info", {"plan": {**plan, "camp_event": {}}})
        self.assertEqual(off, {"enabled": False})
        status, err = self.call("POST", "/api/camps/event-info", {"plan": {**plan, "area": "no_such_area"}})
        self.assertEqual(status, 400)
        self.assertEqual(self.call("POST", "/api/camps/event-info", {"plan": plan}, token=False)[0], 403)

        status, res = self.call("POST", "/api/camps/stage", {"plan": plan})
        self.assertEqual(status, 200, res)
        self.assertTrue(res["ok"], res["issues"])
        self.assertEqual(res["report"]["summary"]["camp_event"]["spots"], 3)
        cid = res["id"]
        rels = {f["rel"] for f in res["files"]}
        self.assertEqual(rels, {"src/git/bandit_cave.git.json", "src/nss/eve_wolf_den.nss", "src/nss/spw_wolf_den.nss"})
        status, applied = self.call("POST", f"/api/changes/{cid}/apply", {})
        self.assertTrue(applied["ok"], applied)
        try:
            text = (self.root / "src/nss/eve_wolf_den.nss").read_text(encoding="utf-8")
            self.assertIn("// tfn-studio camp event: plan wolf_den", text)
            # the dry run now knows the script is ours and the area is wired
            status, again = self.call("POST", "/api/camps/event-info", {"plan": plan})
            self.assertEqual(status, 200, again)
            self.assertEqual(again["wiring"]["slots"], [1])
        finally:
            status, undone = self.call("POST", f"/api/changes/{cid}/undo", {})
            self.assertTrue(undone["ok"], undone)
        self.assertFalse((self.root / "src/nss/eve_wolf_den.nss").exists())
        self.call("POST", f"/api/changes/{cid}/discard", {})

    def test_suggest_spots_endpoint(self):
        plan = json.loads(json.dumps(EVENT_PLAN))
        plan["camp_event"]["spots"] = []
        status, res = self.call("POST", "/api/camps/suggest-spots", {"plan": plan, "count": 4})
        if not self.studio.walkmesh.available():
            self.assertEqual(status, 400)
            self.assertIn("walkmesh", res["error"])
            return
        self.assertEqual(status, 200, res)
        self.assertGreaterEqual(len(res["spots"]), 1)
        grid = self.studio.walkmesh.grid(self.studio.project.read("are", "bandit_cave"))
        for sp in res["spots"]:
            self.assertEqual(grid.at(sp["x"], sp["y"]), 1, sp)                      # open ground
            self.assertIn(sp["facing"] % 360, range(0, 360, 45))
        self.assertEqual(res["spots"], self.call("POST", "/api/camps/suggest-spots", {"plan": plan, "count": 4})[1]["spots"])
        self.assertEqual(self.call("POST", "/api/camps/suggest-spots", {"plan": plan, "count": "many"})[0], 400)

    def test_area_detail_reports_waypoint_facing(self):
        status, area = self.call("GET", "/api/areas/bandit_cave")
        waypoints = [o for o in area["objects"] if o["kind"] == "waypoint"]
        self.assertTrue(all("facing" in w for w in waypoints))
        self.assertIn("event_wps", area)

    def test_quest_stage_and_errors(self):
        status, res = self.call("POST", "/api/quests/describe", {"spec": SPEC})
        self.assertEqual(len(res["stages"]), 5)
        status, res = self.call("POST", "/api/quests/stage", {"spec": SPEC})
        self.assertEqual(status, 200, res)
        self.assertTrue(res["ok"], res["issues"])
        self.assertIn("outline", res["report"]["dialogs"][0])
        self.call("POST", f"/api/changes/{res['id']}/discard", {})
        bad = json.loads(json.dumps(SPEC))
        bad["tag"] = "nope"
        status, err = self.call("POST", "/api/quests/stage", {"spec": bad})
        self.assertEqual(status, 400)
        self.assertIn("tag", err["error"])

    def test_apply_refuses_when_validation_has_errors(self):
        bad = json.loads(json.dumps(PLAN))
        bad["groups"] = [{"n": 3, "ute": "unit_grp", "spawns": 4}]  # group 3 has no markers -> lint error
        status, res = self.call("POST", "/api/camps/stage", {"plan": bad})
        self.assertEqual(status, 200)
        self.assertFalse(res["ok"])
        status, applied = self.call("POST", f"/api/changes/{res['id']}/apply", {})
        self.assertFalse(applied["ok"])
        self.assertTrue(applied["issues"])
        self.call("POST", f"/api/changes/{res['id']}/discard", {})

    def test_prefab_save_roundtrip(self):
        pf = {"id": "unit_prefab", "name": "Unit prefab", "description": "d", "tags": ["t"],
              "items": [{"kind": "placeable", "resref": "plc_barrel", "dx": 1.5, "dy": -2, "facing": 90},
                        {"kind": "marker", "group": 3, "dx": 0, "dy": 4, "facing": 0}]}
        status, res = self.call("POST", "/api/prefabs", {"prefab": pf})
        self.assertEqual(status, 200, res)
        self.assertTrue((Path(self.tmp.name) / "prefabs" / "unit_prefab.json").is_file())
        status, lst = self.call("GET", "/api/prefabs")
        saved = next(p for p in lst if p["id"] == "unit_prefab")
        self.assertEqual(len(saved["items"]), 2)
        self.assertEqual(self.call("POST", "/api/prefabs", {"prefab": {"id": "Bad Id", "items": pf["items"]}})[0], 400)
        self.assertEqual(self.call("POST", "/api/prefabs", {"prefab": {"id": "ok_id", "items": []}})[0], 400)

    # ------------------------------------------------------------------ specs
    def test_spec_store(self):
        status, saved = self.call("POST", "/api/specs/camps", {"spec": PLAN})
        self.assertEqual(saved["id"], "unit_camp")
        status, lst = self.call("GET", "/api/specs/camps")
        self.assertEqual([s["id"] for s in lst], ["unit_camp"])
        status, got = self.call("GET", "/api/specs/camps/unit_camp")
        self.assertEqual(got["area"], "bandit_cave")
        self.assertTrue(self.call("DELETE", "/api/specs/camps/unit_camp")[1]["ok"])
        self.assertEqual(self.call("POST", "/api/specs/camps", {"spec": {"id": "Bad Id"}})[0], 400)
        self.assertEqual(self.call("GET", "/api/specs/camps/..%2fevil")[0], 404)


if __name__ == "__main__":
    unittest.main()
