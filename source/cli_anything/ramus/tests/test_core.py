"""Unit tests for cli-anything-ramus.

Everything here runs on synthetic data with no JVM and no Ramus build, so the
suite stays fast and deterministic. The end-to-end behaviour lives in
``test_full_e2e.py``, which does require the real application.
"""

import json
import os
import sys

import pytest
from click.testing import CliRunner

from cli_anything.ramus.core import arrow as arrow_mod
from cli_anything.ramus.core import classifier as classifier_mod
from cli_anything.ramus.core import export as export_mod
from cli_anything.ramus.core import function as function_mod
from cli_anything.ramus.core import model as model_mod
from cli_anything.ramus.core import preview as preview_mod
from cli_anything.ramus.core import session as session_mod
from cli_anything.ramus.ramus_cli import cli
from cli_anything.ramus.utils import ramus_backend


# --------------------------------------------------------------- fixtures


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


def write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)
    return path


# ================================================== export: verify_output


class TestVerifyOutput:
    """The check that stops a clean exit being mistaken for a good render."""

    def test_accepts_real_png(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.png"), b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        result = export_mod.verify_output(path)
        assert result["valid"] is True
        assert result["size"] > 0

    def test_accepts_real_jpeg(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.jpg"), b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_real_bmp(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.bmp"), b"BM" + b"\x00" * 64)
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_real_pdf(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.pdf"), b"%PDF-1.4\n" + b"x" * 64)
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_svg(self, tmp_dir):
        path = write_bytes(
            os.path.join(tmp_dir, "a.svg"),
            b"<?xml version='1.0'?>\n<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        )
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_emf(self, tmp_dir):
        blob = bytearray(b"\x00" * 64)
        blob[0:4] = b"\x01\x00\x00\x00"
        blob[40:44] = b" EMF"
        path = write_bytes(os.path.join(tmp_dir, "a.emf"), bytes(blob))
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_idl(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.idl"), b"KIT ;\n  IDL VERSION 1.2.8 ;\n")
        assert export_mod.verify_output(path)["valid"] is True

    def test_accepts_rsf(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.rsf"), b"PK\x03\x04" + b"\x00" * 64)
        assert export_mod.verify_output(path)["valid"] is True

    def test_rejects_png_that_is_really_a_pdf(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.png"), b"%PDF-1.4\n" + b"x" * 64)
        result = export_mod.verify_output(path)
        assert result["valid"] is False
        assert "expected" in result["detail"]

    def test_rejects_pdf_that_is_really_html(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.pdf"), b"<html>not a pdf</html>")
        assert export_mod.verify_output(path)["valid"] is False

    def test_rejects_svg_without_svg_element(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.svg"), b"<html><body>nope</body></html>")
        result = export_mod.verify_output(path)
        assert result["valid"] is False
        assert "svg" in result["detail"]

    def test_rejects_emf_without_signature(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.emf"), b"\x00" * 64)
        assert export_mod.verify_output(path)["valid"] is False

    def test_rejects_missing_file(self, tmp_dir):
        result = export_mod.verify_output(os.path.join(tmp_dir, "nope.png"))
        assert result["valid"] is False
        assert result["exists"] is False
        assert result["detail"] == "file does not exist"

    def test_rejects_empty_file(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.png"), b"")
        result = export_mod.verify_output(path)
        assert result["valid"] is False
        assert result["detail"] == "file is empty"

    def test_unknown_extension_is_not_claimed_valid(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.xyz"), b"whatever")
        result = export_mod.verify_output(path)
        assert result["valid"] is False
        assert "no verification rule" in result["detail"]

    def test_jpeg_extension_is_normalised(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "a.jpeg"), b"\xff\xd8\xff" + b"\x00" * 32)
        result = export_mod.verify_output(path)
        assert result["format"] == "jpg"
        assert result["valid"] is True

    def test_explicit_format_overrides_extension(self, tmp_dir):
        path = write_bytes(os.path.join(tmp_dir, "render.out"), b"%PDF-1.7\n" + b"x" * 32)
        assert export_mod.verify_output(path, "pdf")["valid"] is True


class TestHumanSize:
    def test_bytes(self):
        assert export_mod.human_size(512) == "512 B"

    def test_kilobytes(self):
        assert export_mod.human_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert export_mod.human_size(5 * 1024 * 1024) == "5.0 MB"


class TestExportValidation:
    def test_rejects_unknown_image_format(self):
        with pytest.raises(ValueError, match="Unknown image format"):
            export_mod.export_diagram("out.tiff", format="tiff")

    def test_points_pdf_at_its_own_command(self):
        with pytest.raises(ValueError, match="export pdf"):
            export_mod.export_diagram("out.pdf")

    def test_export_all_rejects_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown image format"):
            export_mod.export_all("outdir", format="tiff")


# ============================================================ model logic


class TestRenderTree:
    def test_single_root(self):
        node = {"node": "A0", "name": "Root", "children": []}
        assert model_mod.render_tree(node) == ["A0  Root"]

    def test_flat_children_close_the_branch(self):
        node = {
            "node": "A0",
            "name": "Root",
            "children": [
                {"node": "A1", "name": "One", "children": []},
                {"node": "A2", "name": "Two", "children": []},
            ],
        }
        lines = model_mod.render_tree(node)
        assert lines[0] == "A0  Root"
        assert lines[1].startswith("├─ A1")
        assert lines[2].startswith("└─ A2")

    def test_nested_children_are_indented_under_their_parent(self):
        node = {
            "node": "A0",
            "name": "Root",
            "children": [
                {
                    "node": "A1",
                    "name": "One",
                    "children": [{"node": "A11", "name": "Deep", "children": []}],
                },
                {"node": "A2", "name": "Two", "children": []},
            ],
        }
        lines = model_mod.render_tree(node)
        assert lines[2] == "│  └─ A11  Deep"
        assert lines[3] == "└─ A2  Two"

    def test_last_child_at_every_depth_gets_the_closing_connector(self):
        node = {
            "node": "A0",
            "name": "Root",
            "children": [
                {
                    "node": "A1",
                    "name": "One",
                    "children": [
                        {"node": "A11", "name": "A", "children": []},
                        {"node": "A12", "name": "B", "children": []},
                    ],
                }
            ],
        }
        lines = model_mod.render_tree(node)
        assert lines[1].startswith("└─ A1")
        assert lines[2].startswith("   ├─ A11")
        assert lines[3].startswith("   └─ A12")


class TestModelValidation:
    def test_rejects_unknown_diagram_type(self):
        with pytest.raises(ValueError, match="Unknown diagram type"):
            model_mod.create_model("X", diagram_type="bpmn")

    def test_set_options_refuses_a_no_op(self):
        with pytest.raises(ValueError, match="Nothing to set"):
            model_mod.set_options()


# ========================================================= function logic


class TestFunctionValidation:
    def test_add_rejects_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown function type"):
            function_mod.add_function("Box", type="widget")

    def test_set_type_rejects_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown function type"):
            function_mod.set_type("A1", "widget")

    def test_move_refuses_a_no_op(self):
        with pytest.raises(ValueError, match="--x"):
            function_mod.move_function("A1")

    def test_resize_refuses_a_no_op(self):
        with pytest.raises(ValueError, match="--width"):
            function_mod.resize_function("A1")

    def test_set_color_refuses_a_no_op(self):
        with pytest.raises(ValueError, match="--background"):
            function_mod.set_color("A1")

    def test_set_font_refuses_a_no_op(self):
        with pytest.raises(ValueError, match="--family"):
            function_mod.set_font("A1")

    def test_decompose_rejects_an_empty_child_list(self):
        with pytest.raises(ValueError, match="at least one child name"):
            function_mod.decompose("A1", [])

    def test_every_documented_type_is_accepted(self):
        assert set(function_mod.FUNCTION_TYPES) == {
            "complex", "process", "subprocess", "operation",
            "action", "external", "datastore", "role",
        }


# ============================================================ arrow logic


class TestArrowValidation:
    def test_rejects_unknown_from_side(self):
        with pytest.raises(ValueError, match="--from-side"):
            arrow_mod.add_arrow("A1", "A2", from_side="sideways")

    def test_rejects_unknown_to_side(self):
        with pytest.raises(ValueError, match="--to-side"):
            arrow_mod.add_arrow("A1", "A2", to_side="sideways")

    def test_rejects_border_to_border(self):
        with pytest.raises(ValueError, match="border-to-border"):
            arrow_mod.add_arrow("border", "border")

    def test_border_is_case_insensitive_in_the_check(self):
        with pytest.raises(ValueError, match="border-to-border"):
            arrow_mod.add_arrow("Border", "BORDER")

    def test_idef0_side_names_are_all_available(self):
        for side in ("input", "control", "mechanism", "output"):
            assert side in arrow_mod.SIDES

    def test_geometric_side_aliases_are_available(self):
        for side in ("left", "top", "bottom", "right"):
            assert side in arrow_mod.SIDES


class TestDescribeEndpoint:
    def test_function_endpoint(self):
        text = arrow_mod.describe_endpoint(
            {"kind": "function", "node": "A2", "function": "Assemble", "side": "input"}
        )
        assert text == "A2 Assemble (input)"

    def test_border_endpoint(self):
        assert arrow_mod.describe_endpoint({"kind": "border", "side": "output"}) == "border (output)"

    def test_unset_endpoint(self):
        assert arrow_mod.describe_endpoint({"kind": "unset"}) == "unset"


# ======================================================= classifier logic


class TestRenderElements:
    def test_flat_list(self):
        lines = classifier_mod.render_elements(
            [{"id": 1, "name": "Analyst", "children": []},
             {"id": 2, "name": "Manager", "children": []}]
        )
        assert lines == ["- Analyst  (id 1)", "- Manager  (id 2)"]

    def test_nested_elements_are_indented(self):
        lines = classifier_mod.render_elements(
            [{"id": 1, "name": "Staff",
              "children": [{"id": 2, "name": "Analyst", "children": []}]}]
        )
        assert lines[1] == "  - Analyst  (id 2)"

    def test_empty_list(self):
        assert classifier_mod.render_elements([]) == []


# ========================================================== session logic


class TestSessionId:
    def test_is_stable_for_the_same_path(self, tmp_dir):
        path = os.path.join(tmp_dir, "p.rsf")
        assert session_mod.session_id_for(path) == session_mod.session_id_for(path)

    def test_differs_across_paths(self, tmp_dir):
        a = session_mod.session_id_for(os.path.join(tmp_dir, "a.rsf"))
        b = session_mod.session_id_for(os.path.join(tmp_dir, "b.rsf"))
        assert a != b

    def test_relative_and_absolute_paths_agree(self, tmp_dir, monkeypatch):
        monkeypatch.chdir(tmp_dir)
        assert session_mod.session_id_for("p.rsf") == session_mod.session_id_for(
            os.path.join(tmp_dir, "p.rsf")
        )

    def test_id_is_filesystem_safe(self, tmp_dir):
        path = os.path.join(tmp_dir, "my project (v2).rsf")
        session_id = session_mod.session_id_for(path)
        assert all(c.isalnum() or c in "-_" for c in session_id)


class TestLockedSaveJson:
    def test_writes_valid_json(self, tmp_dir):
        path = os.path.join(tmp_dir, "state.json")
        session_mod._locked_save_json(path, {"a": 1}, indent=2)
        with open(path) as handle:
            assert json.load(handle) == {"a": 1}

    def test_overwrites_a_longer_previous_file_completely(self, tmp_dir):
        path = os.path.join(tmp_dir, "state.json")
        session_mod._locked_save_json(path, {"padding": "x" * 5000})
        session_mod._locked_save_json(path, {"a": 1})
        with open(path) as handle:
            text = handle.read()
        assert json.loads(text) == {"a": 1}
        assert "x" * 100 not in text

    def test_creates_missing_parent_directories(self, tmp_dir):
        path = os.path.join(tmp_dir, "deep", "nested", "state.json")
        session_mod._locked_save_json(path, {"ok": True})
        assert os.path.isfile(path)


class TestSessionState:
    def test_new_session_has_no_project(self):
        session = session_mod.Session()
        assert session.has_project() is False
        assert session.modified is False

    def test_require_project_explains_what_to_do(self):
        session = session_mod.Session()
        with pytest.raises(RuntimeError, match="--project"):
            session.require_project()

    def test_directory_needs_an_id(self):
        session = session_mod.Session()
        with pytest.raises(RuntimeError, match="open or create a project"):
            _ = session.directory

    def test_status_of_an_empty_session(self):
        status = session_mod.Session().status()
        assert status["project_open"] is False
        assert status["undo_available"] == 0
        assert status["max_undo_depth"] == session_mod.MAX_UNDO_DEPTH

    def test_dry_run_defaults_to_off(self):
        assert session_mod.Session().dry_run is False

    def test_list_sessions_tolerates_a_corrupt_state_file(self, tmp_path, monkeypatch):
        root = tmp_path / "sessions"
        (root / "broken").mkdir(parents=True)
        (root / "broken" / "session.json").write_text("{not json")
        (root / "good").mkdir(parents=True)
        (root / "good" / "session.json").write_text(
            json.dumps({"session_id": "good", "project_path": None, "timestamp": 1})
        )
        monkeypatch.setattr(session_mod, "SESSION_ROOT", root)
        sessions = session_mod.Session.list_sessions()
        assert [s["session_id"] for s in sessions] == ["good"]


# ========================================================== backend logic


class TestJarDiscovery:
    def test_env_jar_wins(self, tmp_dir, monkeypatch):
        jar = write_bytes(os.path.join(tmp_dir, "ramus.jar"), b"PK\x03\x04")
        monkeypatch.setenv("RAMUS_JAR", jar)
        assert ramus_backend.find_ramus_jar() == os.path.realpath(jar)

    def test_env_jar_that_does_not_exist_is_rejected(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("RAMUS_JAR", os.path.join(tmp_dir, "missing.jar"))
        with pytest.raises(ramus_backend.RamusNotFound, match="not a file"):
            ramus_backend.find_ramus_jar()

    def test_ramus_home_is_searched(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("RAMUS_JAR", raising=False)
        home = os.path.join(tmp_dir, "ramus")
        os.makedirs(os.path.join(home, "local-client", "build", "libs"))
        jar = write_bytes(os.path.join(home, "local-client", "build", "libs", "ramus.jar"), b"PK")
        monkeypatch.setenv("RAMUS_HOME", home)
        assert ramus_backend.find_ramus_jar() == os.path.realpath(jar)

    def test_empty_ramus_home_is_reported(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("RAMUS_JAR", raising=False)
        monkeypatch.setenv("RAMUS_HOME", tmp_dir)
        with pytest.raises(ramus_backend.RamusNotFound, match="no ramus.jar was found"):
            ramus_backend.find_ramus_jar()

    def test_missing_ramus_gives_install_instructions(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("RAMUS_JAR", raising=False)
        monkeypatch.delenv("RAMUS_HOME", raising=False)
        monkeypatch.setattr(ramus_backend, "JAR_SEARCH_PATHS", ())
        monkeypatch.chdir(tmp_dir)
        with pytest.raises(ramus_backend.RamusNotFound) as excinfo:
            ramus_backend.find_ramus_jar()
        message = str(excinfo.value)
        assert "RAMUS_JAR" in message
        assert "shadowJar" in message

    def test_backend_info_reports_rather_than_raises(self, tmp_dir, monkeypatch):
        monkeypatch.delenv("RAMUS_JAR", raising=False)
        monkeypatch.delenv("RAMUS_HOME", raising=False)
        monkeypatch.setattr(ramus_backend, "JAR_SEARCH_PATHS", ())
        monkeypatch.chdir(tmp_dir)
        info = ramus_backend.backend_info()
        assert info["available"] is False
        assert info["problem"]


class TestBridgeError:
    def test_keeps_the_java_trace(self):
        error = ramus_backend.BridgeError("boom", error_type="java.lang.Error", trace="at Foo.bar")
        assert str(error) == "boom"
        assert error.error_type == "java.lang.Error"
        assert "Foo.bar" in error.trace


# ========================================================== preview logic


class TestPreviewRecipes:
    def test_lists_the_documented_recipes(self):
        recipes = preview_mod.list_recipes()
        assert {r["name"] for r in recipes["recipes"]} == {"diagram", "model", "tree"}

    def test_declares_the_bundle_protocol(self):
        assert preview_mod.list_recipes()["protocol_version"] == "preview-bundle/v1"

    def test_says_live_mode_is_unsupported_and_why(self):
        recipes = preview_mod.list_recipes()
        assert recipes["live_supported"] is False
        assert recipes["live_note"]

    def test_capture_rejects_an_unknown_recipe(self):
        with pytest.raises(ValueError, match="Unknown recipe"):
            preview_mod.capture(recipe="hologram")


# ============================================================ CLI surface


class TestCliSurface:
    def setup_method(self):
        self.runner = CliRunner()

    def test_help_lists_every_group(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for group in ("project", "model", "function", "arrow", "classifier",
                      "element", "export", "import", "preview", "session", "doctor"):
            assert group in result.output

    def test_version(self):
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output

    @pytest.mark.parametrize(
        "group",
        ["project", "model", "function", "arrow", "classifier", "element",
         "export", "import", "preview", "session"],
    )
    def test_group_help(self, group):
        result = self.runner.invoke(cli, [group, "--help"])
        assert result.exit_code == 0

    def test_json_flag_is_accepted(self):
        result = self.runner.invoke(cli, ["--json", "--help"])
        assert result.exit_code == 0

    def test_dry_run_flag_is_documented(self):
        result = self.runner.invoke(cli, ["--help"])
        assert "--dry-run" in result.output

    def test_arrow_add_help_documents_idef0_sides(self):
        result = self.runner.invoke(cli, ["arrow", "add", "--help"])
        assert result.exit_code == 0
        assert "control" in result.output
        assert "mechanism" in result.output


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
