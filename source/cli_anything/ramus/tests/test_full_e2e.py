"""End-to-end tests for cli-anything-ramus.

Every test here drives the real Ramus engine and inspects the real files it
writes. There is no graceful degradation: without a Ramus build these tests
fail, because a CLI that cannot reach Ramus is not doing its job.

    export RAMUS_JAR=/path/to/ramus.jar
    CLI_ANYTHING_FORCE_INSTALLED=1 python3 -m pytest cli_anything/ramus/tests/ -v -s

The ``-s`` flag prints every artifact path so the results can be opened and
looked at.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

from cli_anything.ramus.core import arrow as arrow_mod
from cli_anything.ramus.core import classifier as classifier_mod
from cli_anything.ramus.core import export as export_mod
from cli_anything.ramus.core import function as function_mod
from cli_anything.ramus.core import model as model_mod
from cli_anything.ramus.core import preview as preview_mod
from cli_anything.ramus.core import project as project_mod
from cli_anything.ramus.core import session as session_mod
from cli_anything.ramus.utils import ramus_backend


# --------------------------------------------------------------- helpers


def _resolve_cli(name):
    """Resolve installed CLI command; falls back to python -m for dev.

    Set env CLI_ANYTHING_FORCE_INSTALLED=1 to require the installed command.
    """
    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        print(f"[_resolve_cli] Using installed command: {path}")
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    module = "cli_anything.ramus"
    print(f"[_resolve_cli] Falling back to: {sys.executable} -m {module}")
    return [sys.executable, "-m", module]


def artifact(label, path):
    """Print an artifact path so a human can go and look at it."""
    size = os.path.getsize(path) if os.path.isfile(path) else 0
    print(f"\n  {label}: {path} ({size:,} bytes)")


def read_png(path):
    """Decode a PNG far enough to reason about its pixels.

    Written by hand rather than with Pillow so the suite has no image
    dependency: a render check must not itself be the thing that is missing.
    Returns ``(width, height, rows)`` where each row is a list of (r, g, b).
    """
    with open(path, "rb") as handle:
        data = handle.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"

    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
        pos += 12 + length

    assert bit_depth == 8, f"expected 8-bit samples, got {bit_depth}"
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    raw = zlib.decompress(bytes(idat))

    stride = width * channels
    rows = []
    previous = bytearray(stride)
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else up_left)
                line[i] = (line[i] + pred) & 0xFF
        rows.append(
            [tuple(line[i:i + 3]) if channels >= 3 else (line[i],) * 3
             for i in range(0, stride, channels)]
        )
        previous = line
    return width, height, rows


def pixel_stats(path):
    """Summarise a rendered diagram: size, ink coverage, distinct colours."""
    width, height, rows = read_png(path)
    total = width * height
    white = 0
    colours = set()
    for row in rows:
        for pixel in row:
            if pixel == (255, 255, 255):
                white += 1
            colours.add(pixel)
    return {
        "width": width,
        "height": height,
        "pixels": total,
        "white_fraction": white / total,
        "ink_fraction": 1.0 - (white / total),
        "distinct_colours": len(colours),
        "rows": rows,
    }


# -------------------------------------------------------------- fixtures


@pytest.fixture(scope="session", autouse=True)
def require_ramus():
    """The real application is a hard dependency; say so plainly if absent."""
    info = ramus_backend.backend_info()
    if not info["available"]:
        pytest.fail(
            "These end-to-end tests need a real Ramus build and a JDK.\n" + (info["problem"] or "")
        )
    print(f"\n[backend] ramus.jar: {info['ramus_jar']}")
    return info


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """Give each test its own session store, and a clean session object."""
    monkeypatch.setattr(session_mod, "SESSION_ROOT", tmp_path / "sessions")
    session_mod.reset_session()
    yield
    session_mod.reset_session()


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def project(tmp_dir):
    """A fresh project with one IDEF0 model."""
    path = os.path.join(tmp_dir, "project.rsf")
    project_mod.new_project(path, model_name="Test model", author="pytest", overwrite=True)
    return path


@pytest.fixture
def three_box_model(project):
    """A0 decomposed into three activities, with the usual IDEF0 arrows."""
    function_mod.add_function("Receive order")
    function_mod.add_function("Assemble")
    function_mod.add_function("Ship")
    arrow_mod.add_arrow("Receive order", "Assemble", name="Confirmed order")
    arrow_mod.add_arrow("Assemble", "Ship", name="Packed goods")
    arrow_mod.add_arrow("border", "Receive order", name="Customer order", from_side="input")
    arrow_mod.add_arrow("Ship", "border", name="Delivery", to_side="output")
    project_mod.save_project()
    return project


# ================================================== project lifecycle


class TestProjectLifecycle:
    def test_new_project_writes_a_real_rsf(self, tmp_dir):
        path = os.path.join(tmp_dir, "new.rsf")
        result = project_mod.new_project(path, model_name="Order flow", author="QA",
                                         project="Demo", overwrite=True)
        artifact("project", result["path"])
        assert os.path.isfile(result["path"])
        assert result["file_size"] > 1000
        with open(result["path"], "rb") as handle:
            assert handle.read(4) == b"PK\x03\x04", "a .rsf must be a ZIP archive"

    def test_new_project_contains_what_was_asked_for(self, tmp_dir):
        path = os.path.join(tmp_dir, "new.rsf")
        result = project_mod.new_project(
            path, model_name="Order flow", classifiers=["Roles", "Documents"], overwrite=True
        )
        assert [m["name"] for m in result["models"]] == ["Order flow"]
        assert {c["name"] for c in result["classifiers"]} == {"Roles", "Documents"}

    def test_reopening_in_a_fresh_engine_returns_the_same_model(self, tmp_dir):
        path = os.path.join(tmp_dir, "new.rsf")
        project_mod.new_project(path, model_name="Order flow", overwrite=True)
        function_mod.add_function("Step one")
        project_mod.save_project()

        session_mod.reset_session()
        info = project_mod.open_project(path)
        assert info["models"][0]["name"] == "Order flow"
        assert [f["name"] for f in function_mod.list_functions()["functions"]][1:] == ["Step one"]

    def test_save_as_writes_a_second_working_file(self, project, tmp_dir):
        other = os.path.join(tmp_dir, "copy.rsf")
        result = project_mod.save_project(other)
        artifact("save-as", result["path"])
        session_mod.reset_session()
        assert project_mod.open_project(other)["models"][0]["name"] == "Test model"

    def test_validate_accepts_a_real_project(self, three_box_model):
        result = project_mod.validate()
        assert result["valid"] is True
        assert result["problems"] == []
        assert result["function_count"] == 4
        assert result["arrow_count"] == 4

    def test_creating_over_an_existing_file_is_refused(self, project):
        with pytest.raises(Exception, match="already exists"):
            project_mod.new_project(project, overwrite=False)

    def test_project_info_counts_everything(self, three_box_model):
        info = project_mod.project_info()
        assert info["model_count"] == 1
        assert info["function_count"] == 4
        assert info["arrow_count"] == 4


# ============================================================== models


class TestModels:
    def test_create_each_notation(self, project):
        for name, notation in (("Flow", "dfd"), ("Roles", "dfds"), ("Process", "idef0")):
            created = model_mod.create_model(name, notation)
            assert created["diagram_type"] == notation
        assert model_mod.list_models()["count"] == 4

    def test_notation_survives_a_round_trip(self, project):
        model_mod.create_model("Flow", "dfd")
        project_mod.save_project()
        session_mod.reset_session()
        project_mod.open_project(project)
        assert model_mod.model_info("Flow")["diagram_type"] == "dfd"

    def test_rename(self, project):
        result = model_mod.rename_model("Renamed")
        assert result["previous_name"] == "Test model"
        assert model_mod.list_models()["models"][0]["name"] == "Renamed"

    def test_delete(self, project):
        model_mod.create_model("Second")
        model_mod.delete_model("Second")
        assert [m["name"] for m in model_mod.list_models()["models"]] == ["Test model"]

    def test_options_survive_a_round_trip(self, project):
        model_mod.set_options(author="Ada", project="Looms", definition="Weaving",
                              used_at="Mill")
        project_mod.save_project()
        session_mod.reset_session()
        project_mod.open_project(project)
        options = model_mod.model_info()["options"]
        assert options["author"] == "Ada"
        assert options["project"] == "Looms"
        assert options["definition"] == "Weaving"
        assert options["used_at"] == "Mill"

    def test_selectable_by_id_and_by_name(self, project):
        model_id = model_mod.list_models()["models"][0]["id"]
        assert model_mod.model_info(str(model_id))["name"] == "Test model"
        assert model_mod.model_info("Test model")["id"] == model_id

    def test_ambiguous_selection_names_the_candidates(self, project):
        model_mod.create_model("Second")
        with pytest.raises(Exception) as excinfo:
            function_mod.list_functions()
        message = str(excinfo.value)
        assert "--model" in message
        assert "Second" in message


# =========================================================== functions


class TestFunctions:
    def test_boxes_get_idef0_node_numbers_in_order(self, project):
        for name in ("First", "Second", "Third"):
            function_mod.add_function(name)
        nodes = [f["node"] for f in function_mod.list_functions()["functions"]]
        assert nodes == ["A0", "A1", "A2", "A3"]

    def test_decompose_numbers_children_under_their_parent(self, project):
        function_mod.add_function("Assemble")
        function_mod.decompose("A1", ["Pick", "Build", "Test"])
        children = function_mod.list_functions(parent="A1", recursive=False)["functions"]
        assert [c["node"] for c in children] == ["A11", "A12", "A13"]
        assert function_mod.function_info("A1")["decomposed"] is True

    def test_default_layout_keeps_six_boxes_on_the_page(self, project):
        for i in range(6):
            function_mod.add_function(f"Step {i}")
        for box in function_mod.list_functions(recursive=False)["functions"]:
            bounds = box["bounds"]
            assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 800
            assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 444

    def test_rename(self, project):
        function_mod.add_function("Old name")
        result = function_mod.rename_function("A1", "New name")
        assert result["previous_name"] == "Old name"
        assert function_mod.function_info("A1")["name"] == "New name"

    def test_renaming_a0_renames_the_model(self, project):
        function_mod.rename_function("A0", "Whole process")
        assert model_mod.list_models()["models"][0]["name"] == "Whole process"

    def test_move_and_resize_are_read_back(self, project):
        function_mod.add_function("Box")
        function_mod.move_function("A1", x=120, y=200)
        function_mod.resize_function("A1", width=250, height=150)
        bounds = function_mod.function_info("A1")["bounds"]
        assert (bounds["x"], bounds["y"], bounds["width"], bounds["height"]) == (120, 200, 250, 150)

    def test_bounds_survive_a_round_trip(self, project):
        function_mod.add_function("Box")
        function_mod.move_function("A1", x=333, y=222)
        project_mod.save_project()
        session_mod.reset_session()
        project_mod.open_project(project)
        bounds = function_mod.function_info("A1")["bounds"]
        assert (bounds["x"], bounds["y"]) == (333, 222)

    def test_colours_are_read_back(self, project):
        function_mod.add_function("Box")
        result = function_mod.set_color("A1", background="#ffcc00", foreground="#003366")
        assert result["background"] == "#ffcc00"
        assert result["foreground"] == "#003366"

    def test_font_is_read_back(self, project):
        function_mod.add_function("Box")
        result = function_mod.set_font("A1", family="Serif", size=14, bold=True)
        assert result["font"]["size"] == 14
        assert result["font"]["bold"] is True

    def test_type_is_read_back(self, project):
        function_mod.add_function("Box")
        assert function_mod.set_type("A1", "operation")["type"] == "operation"

    def test_delete_removes_the_box(self, project):
        function_mod.add_function("Keep")
        function_mod.add_function("Drop")
        function_mod.delete_function("A2")
        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["Keep"]

    def test_delete_removes_the_subtree(self, project):
        function_mod.add_function("Parent")
        function_mod.decompose("A1", ["Child one", "Child two"])
        function_mod.delete_function("A1")
        assert function_mod.list_functions()["count"] == 1  # only A0 remains

    def test_deleting_the_base_function_is_refused(self, project):
        with pytest.raises(Exception, match="base function"):
            function_mod.delete_function("A0")

    def test_selectable_by_id_node_and_name(self, project):
        created = function_mod.add_function("Findable")
        assert function_mod.function_info(str(created["id"]))["name"] == "Findable"
        assert function_mod.function_info("A1")["name"] == "Findable"
        assert function_mod.function_info("Findable")["node"] == "A1"


# ============================================================== arrows


class TestArrows:
    def test_box_to_box(self, project):
        function_mod.add_function("One")
        function_mod.add_function("Two")
        result = arrow_mod.add_arrow("One", "Two", name="Handover")
        assert result["from"]["kind"] == "function"
        assert result["from"]["node"] == "A1"
        assert result["from"]["side"] == "output"
        assert result["to"]["node"] == "A2"
        assert result["to"]["side"] == "input"
        assert result["name"] == "Handover"

    def test_border_into_a_box_is_an_input(self, project):
        function_mod.add_function("One")
        result = arrow_mod.add_arrow("border", "One", name="Raw material", from_side="input")
        assert result["from"]["kind"] == "border"
        assert result["to"]["side"] == "input"

    def test_box_out_to_the_border_is_an_output(self, project):
        function_mod.add_function("One")
        result = arrow_mod.add_arrow("One", "border", name="Product", to_side="output")
        assert result["to"]["kind"] == "border"

    def test_control_arrives_on_the_top_side(self, project):
        function_mod.add_function("One")
        result = arrow_mod.add_arrow("border", "One", name="Policy",
                                     from_side="control", to_side="control")
        assert result["to"]["side"] == "control"

    def test_mechanism_arrives_on_the_bottom_side(self, project):
        function_mod.add_function("One")
        result = arrow_mod.add_arrow("border", "One", name="Team",
                                     from_side="mechanism", to_side="mechanism")
        assert result["to"]["side"] == "mechanism"

    def test_rename_updates_the_arrow_dictionary(self, three_box_model):
        arrows = arrow_mod.list_arrows()["arrows"]
        target = next(a for a in arrows if a["name"] == "Packed goods")
        arrow_mod.rename_arrow(str(target["id"]), "Boxed goods")
        assert "Boxed goods" in {s["name"] for s in arrow_mod.list_streams()["streams"]}

    def test_delete_leaves_the_others_resolvable(self, three_box_model):
        arrows = arrow_mod.list_arrows()["arrows"]
        arrow_mod.delete_arrow(str(arrows[0]["id"]))
        remaining = arrow_mod.list_arrows()["arrows"]
        assert len(remaining) == len(arrows) - 1
        for a in remaining:
            assert a["from"]["kind"] in ("function", "border")

    def test_connecting_boxes_from_different_diagrams_is_refused(self, project):
        function_mod.add_function("Top")
        function_mod.decompose("A1", ["Deep"])
        with pytest.raises(Exception, match="not a child of diagram"):
            arrow_mod.add_arrow("Top", "Deep")

    def test_arrows_survive_a_round_trip(self, three_box_model):
        before = arrow_mod.list_arrows()["arrows"]
        session_mod.reset_session()
        project_mod.open_project(three_box_model)
        after = arrow_mod.list_arrows()["arrows"]
        assert len(after) == len(before)
        assert {a["name"] for a in after} == {a["name"] for a in before}
        for a in after:
            assert a["from"]["kind"] != "unset"
            assert a["to"]["kind"] != "unset"

    def test_arrows_are_listable_per_diagram(self, three_box_model):
        function_mod.decompose("A2", ["Inner one", "Inner two"])
        arrow_mod.add_arrow("Inner one", "Inner two", name="Inner flow", diagram="A2")
        top = arrow_mod.list_arrows(diagram="A0")["arrows"]
        inner = arrow_mod.list_arrows(diagram="A2")["arrows"]
        assert len(top) == 4
        assert [a["name"] for a in inner] == ["Inner flow"]


# =========================================================== rendering


class TestRendering:
    @pytest.mark.parametrize("fmt", ["png", "jpg", "bmp", "svg"])
    def test_every_image_format_renders_and_verifies(self, three_box_model, tmp_dir, fmt):
        out = os.path.join(tmp_dir, f"diagram.{fmt}")
        result = export_mod.export_diagram(out, overwrite=True)
        artifact(fmt.upper(), result["output"])
        check = export_mod.verify_output(result["output"], fmt)
        assert check["valid"], check["detail"]
        assert result["file_size"] > 500

    def test_emf_reports_that_it_needs_a_display(self, three_box_model, tmp_dir):
        """Ramus's EMF writer cannot run headlessly; say why, do not pretend.

        FreeHEP asks the toolkit for the screen size while writing the EMF
        header. Asserted rather than skipped so the suite notices if a future
        Ramus or FreeHEP removes that call.
        """
        out = os.path.join(tmp_dir, "diagram.emf")
        if os.environ.get("CLI_ANYTHING_RAMUS_HEADLESS", "1").strip() == "0":
            result = export_mod.export_diagram(out, overwrite=True)
            artifact("EMF", result["output"])
            assert export_mod.verify_output(result["output"], "emf")["valid"]
            return
        with pytest.raises(Exception, match="needs a graphics display"):
            export_mod.export_diagram(out, overwrite=True)

    def test_formats_flags_emf_as_display_only(self, project):
        formats = export_mod.formats()
        assert formats["needs_display"] == ["emf"]
        assert "emf" not in formats["raster"] + formats["vector"]

    def test_png_is_a_real_diagram_not_a_blank_page(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "a0.png")
        export_mod.export_diagram(out, overwrite=True)
        artifact("PNG analysed", out)
        stats = pixel_stats(out)
        print(f"  {stats['width']}x{stats['height']}, ink {stats['ink_fraction']:.4f}, "
              f"{stats['distinct_colours']} distinct colours")
        assert stats["width"] > 800 and stats["height"] > 500
        # An IDEF0 sheet is mostly white paper...
        assert stats["white_fraction"] > 0.5
        # ...but a blank page would mean the painter drew nothing.
        assert stats["ink_fraction"] > 0.005
        assert stats["distinct_colours"] > 2

    def test_adding_a_box_changes_the_render(self, three_box_model, tmp_dir):
        first = os.path.join(tmp_dir, "before.png")
        second = os.path.join(tmp_dir, "after.png")
        export_mod.export_diagram(first, overwrite=True)
        function_mod.add_function("Invoice customer")
        project_mod.save_project()
        export_mod.export_diagram(second, overwrite=True)
        artifact("before", first)
        artifact("after", second)
        with open(first, "rb") as a, open(second, "rb") as b:
            assert a.read() != b.read(), "the render ignored the new box"
        assert pixel_stats(second)["ink_fraction"] > pixel_stats(first)["ink_fraction"]

    def test_box_colour_reaches_the_painter(self, three_box_model, tmp_dir):
        plain = os.path.join(tmp_dir, "plain.png")
        export_mod.export_diagram(plain, overwrite=True)
        before = pixel_stats(plain)

        function_mod.set_color("A1", background="#ff0000")
        project_mod.save_project()
        coloured = os.path.join(tmp_dir, "coloured.png")
        export_mod.export_diagram(coloured, overwrite=True)
        after = pixel_stats(coloured)
        artifact("coloured", coloured)

        reds = sum(
            1 for row in after["rows"] for p in row
            if p[0] > 200 and p[1] < 80 and p[2] < 80
        )
        print(f"  red pixels after colouring: {reds:,}")
        assert reds > 100, "the box fill colour never reached the render"
        assert after["white_fraction"] < before["white_fraction"]

    def test_svg_contains_drawing_elements(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "a0.svg")
        export_mod.export_diagram(out, overwrite=True)
        artifact("SVG", out)
        with open(out, encoding="utf-8") as handle:
            svg = handle.read()
        assert "<svg" in svg
        assert any(tag in svg for tag in ("<path", "<rect", "<line", "<polyline", "<g "))
        assert len(svg) > 2000

    def test_render_size_is_honoured(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "wide.png")
        export_mod.export_diagram(out, width=2400, height=1600, overwrite=True)
        stats = pixel_stats(out)
        assert stats["width"] > 2000

    def test_pdf_has_one_page_per_diagram(self, three_box_model, tmp_dir):
        function_mod.decompose("A2", ["Inner one", "Inner two"])
        project_mod.save_project()
        out = os.path.join(tmp_dir, "model.pdf")
        result = export_mod.export_pdf(out, overwrite=True)
        artifact("PDF", result["output"])
        assert export_mod.verify_output(result["output"], "pdf")["valid"]
        assert result["page_count"] == 2
        assert {p["diagram_node"] for p in result["pages"]} == {"A0", "A2"}

    def test_pdf_of_a_single_diagram_has_one_page(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "one.pdf")
        result = export_mod.export_pdf(out, diagram="A0", overwrite=True)
        assert result["page_count"] == 1
        assert export_mod.verify_output(result["output"], "pdf")["valid"]

    def test_export_all_writes_one_file_per_diagram(self, three_box_model, tmp_dir):
        function_mod.decompose("A2", ["Inner one", "Inner two"])
        project_mod.save_project()
        outdir = os.path.join(tmp_dir, "images")
        result = export_mod.export_all(outdir, overwrite=True)
        assert result["count"] == 2
        for output in result["outputs"]:
            artifact(output["diagram_node"], output["output"])
            assert export_mod.verify_output(output["output"], "png")["valid"]
            assert output["diagram_node"] in os.path.basename(output["output"])

    def test_rendering_a_leaf_box_is_refused_with_advice(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "leaf.png")
        with pytest.raises(Exception, match="no child boxes"):
            export_mod.export_diagram(out, diagram="A1", overwrite=True)

    def test_overwrite_is_required_to_replace_a_file(self, three_box_model, tmp_dir):
        out = os.path.join(tmp_dir, "a0.png")
        export_mod.export_diagram(out, overwrite=True)
        with pytest.raises(Exception, match="already exists"):
            export_mod.export_diagram(out, overwrite=False)

    def test_formats_names_the_real_renderer(self, project):
        formats = export_mod.formats()
        assert "png" in formats["raster"]
        assert "pdf" in formats["vector"]
        assert "PIDEF0painter" in formats["renderer"]


# ========================================================= interchange


class TestIdl:
    def test_export_of_an_unlabelled_model_succeeds(self, project, tmp_dir):
        function_mod.add_function("Step one")
        function_mod.add_function("Step two")
        arrow_mod.add_arrow("Step one", "Step two")
        out = os.path.join(tmp_dir, "model.idl")
        result = export_mod.export_idl(out, overwrite=True)
        artifact("IDL", result["output"])
        assert export_mod.verify_output(result["output"], "idl")["valid"]

    def test_export_of_a_labelled_model_reports_the_upstream_defect(self, three_box_model, tmp_dir):
        """Ramus's IDL writer crashes on labelled arrows.

        Asserted rather than skipped, so this suite notices if Ramus ever fixes
        it and the CLI's workaround becomes stale.
        """
        out = os.path.join(tmp_dir, "labelled.idl")
        with pytest.raises(Exception) as excinfo:
            export_mod.export_idl(out, overwrite=True)
        assert "defect in Ramus itself" in str(excinfo.value)

    def test_import_of_a_context_named_file_succeeds(self, project, tmp_dir):
        function_mod.add_function("Step one")
        function_mod.add_function("Step two")
        arrow_mod.add_arrow("Step one", "Step two")
        exported = os.path.join(tmp_dir, "model.idl")
        export_mod.export_idl(exported, overwrite=True)

        # Ramus's importer expects the IDEF0 context section to be named A-0.
        fixed = os.path.join(tmp_dir, "fixed.idl")
        with open(exported, encoding="utf-8") as handle:
            text = handle.read()
        with open(fixed, "w", encoding="utf-8") as handle:
            handle.write(text.replace("DIAGRAM GRAPHIC A0 ;", "DIAGRAM GRAPHIC A-0 ;"))

        result = export_mod.import_idl(fixed, name="Imported", encoding="UTF-8")
        assert result["imported"] is True
        assert result["function_count"] >= 2
        assert model_mod.list_models()["count"] == 2

    def test_import_of_ramus_own_export_reports_the_mismatch(self, project, tmp_dir):
        """Ramus writes 'A0' where its own importer requires 'A-0'."""
        function_mod.add_function("Step one")
        function_mod.add_function("Step two")
        arrow_mod.add_arrow("Step one", "Step two")
        exported = os.path.join(tmp_dir, "model.idl")
        export_mod.export_idl(exported, overwrite=True)

        with pytest.raises(Exception) as excinfo:
            export_mod.import_idl(exported, name="Imported", encoding="UTF-8")
        assert "A-0" in str(excinfo.value)


# ========================================================== undo / redo


class TestUndoRedo:
    def test_undo_removes_the_last_change_from_disk(self, project):
        function_mod.add_function("Keep")
        project_mod.save_project()
        function_mod.add_function("Remove")
        project_mod.save_project()

        session_mod.get_session().undo()
        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["Keep"]

        session_mod.reset_session()
        project_mod.open_project(project)
        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["Keep"], "undo did not reach the file on disk"

    def test_redo_restores_it(self, project):
        function_mod.add_function("Keep")
        function_mod.add_function("Remove")
        session = session_mod.get_session()
        session.undo()
        session.redo()
        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["Keep", "Remove"]

    def test_history_is_shared_across_sessions_for_the_same_file(self, project):
        function_mod.add_function("Keep")
        function_mod.add_function("Remove")
        project_mod.save_project()

        # A separate session, as a second one-shot command would create.
        session_mod.reset_session()
        project_mod.open_project(project)
        session_mod.get_session().undo()
        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["Keep"]

    def test_undo_with_no_history_says_so(self, project):
        session_mod.reset_session()
        project_mod.open_project(project)
        with pytest.raises(RuntimeError, match="Nothing to undo"):
            session_mod.get_session().undo()

    def test_history_lists_real_snapshot_files(self, project):
        function_mod.add_function("One")
        history = session_mod.get_session().history()
        assert history["undo_available"] >= 1
        for entry in history["undo"]:
            assert entry["exists"] is True
            assert entry["size"] > 1000


# ============================================================ previews


class TestPreviews:
    def test_capture_publishes_a_valid_bundle(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        manifest = preview_mod.capture(root_dir=root)
        artifact("bundle", manifest["_bundle_dir"])
        assert manifest["protocol_version"] == "preview-bundle/v1"
        assert manifest["status"] == "ok"
        assert os.path.isfile(manifest["_manifest_path"])
        assert os.path.isfile(manifest["_summary_path"])
        for art in manifest["artifacts"]:
            path = os.path.join(manifest["_bundle_dir"], art["path"])
            assert os.path.isfile(path), art["path"]
            if art["kind"] == "image":
                assert export_mod.verify_output(path)["valid"]

    def test_capture_reuses_a_bundle_when_nothing_changed(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        first = preview_mod.capture(root_dir=root)
        second = preview_mod.capture(root_dir=root)
        assert second["_cached"] is True
        assert second["bundle_id"] == first["bundle_id"]

    def test_force_renders_a_new_bundle(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        first = preview_mod.capture(root_dir=root)
        forced = preview_mod.capture(root_dir=root, force=True)
        assert forced["_cached"] is False
        assert forced["bundle_id"] != first["bundle_id"]

    def test_editing_the_model_produces_a_new_bundle(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        first = preview_mod.capture(root_dir=root)
        function_mod.add_function("Extra")
        second = preview_mod.capture(root_dir=root)
        assert second["bundle_id"] != first["bundle_id"]
        assert second["_cached"] is False

    def test_latest_returns_the_newest_without_rendering(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        published = preview_mod.capture(root_dir=root)
        latest = preview_mod.latest(root_dir=root)
        assert latest["bundle_id"] == published["bundle_id"]

    def test_model_recipe_renders_every_diagram(self, three_box_model, tmp_dir):
        function_mod.decompose("A2", ["Inner one", "Inner two"])
        root = os.path.join(tmp_dir, "previews")
        manifest = preview_mod.capture(recipe="model", root_dir=root)
        images = [a for a in manifest["artifacts"] if a["kind"] == "image"]
        assert {a["diagram_node"] for a in images} == {"A0", "A2"}

    def test_tree_recipe_publishes_inspection_only(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        manifest = preview_mod.capture(recipe="tree", root_dir=root)
        kinds = {a["kind"] for a in manifest["artifacts"]}
        assert kinds == {"inspection"}

    def test_diff_reports_the_structural_change(self, three_box_model, tmp_dir):
        baseline = os.path.join(tmp_dir, "baseline.rsf")
        shutil.copy(three_box_model, baseline)
        function_mod.add_function("Extra step")
        project_mod.save_project()

        root = os.path.join(tmp_dir, "previews")
        manifest = preview_mod.diff(baseline, root_dir=root)
        artifact("diff bundle", manifest["_bundle_dir"])
        assert manifest["bundle_kind"] == "diff"
        with open(manifest["_summary_path"], encoding="utf-8") as handle:
            summary = json.load(handle)
        assert summary["identical"] is False
        assert summary["changed"]["function_count"]["current"] > \
            summary["changed"]["function_count"]["baseline"]

    def test_recipes_are_all_capturable(self, three_box_model, tmp_dir):
        root = os.path.join(tmp_dir, "previews")
        for recipe in preview_mod.RECIPES:
            manifest = preview_mod.capture(recipe=recipe, root_dir=root)
            assert manifest["recipe"] == recipe


# ================================================ classifiers and data


class TestClassifiers:
    def test_create_and_list(self, project):
        classifier_mod.create_classifier("Roles")
        classifier_mod.create_classifier("Documents")
        names = {c["name"] for c in classifier_mod.list_classifiers()["classifiers"]}
        assert {"Roles", "Documents"} <= names

    def test_elements_nest(self, project):
        classifier_mod.create_classifier("Roles")
        parent = classifier_mod.add_element("Roles", "Staff")
        classifier_mod.add_element("Roles", "Analyst", parent=str(parent["id"]))
        shown = classifier_mod.show_classifier("Roles")
        staff = next(e for e in shown["elements"] if e["name"] == "Staff")
        assert [c["name"] for c in staff["children"]] == ["Analyst"]

    def test_elements_survive_a_round_trip(self, project):
        classifier_mod.create_classifier("Roles")
        classifier_mod.add_element("Roles", "Analyst")
        project_mod.save_project()
        session_mod.reset_session()
        project_mod.open_project(project)
        names = [e["name"] for e in classifier_mod.list_elements("Roles")["elements"]]
        assert names == ["Analyst"]

    def test_rename_and_delete(self, project):
        classifier_mod.create_classifier("Roles")
        classifier_mod.add_element("Roles", "Analist")
        element_id = classifier_mod.list_elements("Roles")["elements"][0]["id"]
        classifier_mod.rename_element("Roles", str(element_id), "Analyst")
        assert classifier_mod.list_elements("Roles")["elements"][0]["name"] == "Analyst"
        classifier_mod.delete_element("Roles", str(element_id))
        assert classifier_mod.list_elements("Roles")["count"] == 0

    def test_duplicate_classifier_name_is_refused(self, project):
        classifier_mod.create_classifier("Roles")
        with pytest.raises(Exception, match="already exists"):
            classifier_mod.create_classifier("Roles")


# ================================================== realistic workflows


class TestWorkflows:
    def test_order_fulfilment_model_built_and_published(self, tmp_dir):
        """An analyst models a business process from nothing and publishes it."""
        path = os.path.join(tmp_dir, "fulfilment.rsf")
        project_mod.new_project(
            path, model_name="Fulfil customer order", author="Analyst",
            project="Order fulfilment", classifiers=["Roles", "Documents"], overwrite=True,
        )

        function_mod.add_function("Receive order")
        function_mod.add_function("Assemble goods")
        function_mod.add_function("Ship goods")

        arrow_mod.add_arrow("border", "Receive order", name="Customer order", from_side="input")
        arrow_mod.add_arrow("Receive order", "Assemble goods", name="Confirmed order")
        arrow_mod.add_arrow("Assemble goods", "Ship goods", name="Packed goods")
        arrow_mod.add_arrow("Ship goods", "border", name="Delivered goods", to_side="output")
        arrow_mod.add_arrow("border", "Assemble goods", name="Build specification",
                            from_side="control", to_side="control")

        function_mod.decompose("Assemble goods", ["Pick parts", "Build unit", "Test unit"])
        arrow_mod.add_arrow("Pick parts", "Build unit", name="Parts", diagram="Assemble goods")
        arrow_mod.add_arrow("Build unit", "Test unit", name="Assembled unit",
                            diagram="Assemble goods")

        model_mod.set_options(author="Analyst", project="Order fulfilment",
                              definition="How a customer order becomes a delivery")
        project_mod.save_project()

        tree = model_mod.model_tree()["root"]
        assert [c["node"] for c in tree["children"]] == ["A1", "A2", "A3"]
        assert [c["node"] for c in tree["children"][1]["children"]] == ["A21", "A22", "A23"]

        top = arrow_mod.list_arrows(diagram="A0")["arrows"]
        assert len(top) == 5
        controls = [a for a in top if a["to"].get("side") == "control"]
        assert len(controls) == 1

        images = os.path.join(tmp_dir, "diagrams")
        rendered = export_mod.export_all(images, overwrite=True)
        assert rendered["count"] == 2
        for output in rendered["outputs"]:
            artifact(output["diagram_node"], output["output"])
            assert export_mod.verify_output(output["output"], "png")["valid"]
            assert pixel_stats(output["output"])["ink_fraction"] > 0.005

        pdf = os.path.join(tmp_dir, "fulfilment.pdf")
        pdf_result = export_mod.export_pdf(pdf, overwrite=True)
        artifact("PDF", pdf_result["output"])
        assert pdf_result["page_count"] == 2
        assert export_mod.verify_output(pdf, "pdf")["valid"]

        session_mod.reset_session()
        reopened = project_mod.open_project(path)
        assert reopened["function_count"] == 7
        assert reopened["arrow_count"] == 7

    def test_iterative_refinement_loop(self, tmp_dir):
        """The look-edit-look loop an agent runs while building a model."""
        path = os.path.join(tmp_dir, "iterate.rsf")
        project_mod.new_project(path, model_name="Iterate", overwrite=True)
        function_mod.add_function("First")
        function_mod.add_function("Second")
        project_mod.save_project()

        root = os.path.join(tmp_dir, "previews")
        first = preview_mod.capture(root_dir=root)

        function_mod.add_function("Third")
        second = preview_mod.capture(root_dir=root)
        assert second["bundle_id"] != first["bundle_id"]

        session_mod.get_session().undo()
        third = preview_mod.capture(root_dir=root)

        # Each bundle is content-addressed by the .rsf file, and Ramus stamps a
        # fresh revision date when it saves, so undo yields a new bundle rather
        # than the original one. What must match is the picture and the model.
        assert third["bundle_id"] not in (first["bundle_id"], second["bundle_id"])

        def png_of(manifest):
            image = next(a for a in manifest["artifacts"]
                         if a["kind"] == "image" and a["path"].endswith(".png"))
            with open(os.path.join(manifest["_bundle_dir"], image["path"]), "rb") as handle:
                return handle.read()

        assert png_of(third) == png_of(first), \
            "after undo the diagram should render exactly as it did before the edit"
        assert png_of(second) != png_of(first)

        names = [f["name"] for f in function_mod.list_functions(recursive=False)["functions"]]
        assert names == ["First", "Second"]

    def test_review_pass_over_an_existing_project(self, three_box_model, tmp_dir):
        """Picking up someone else's file from a cold start."""
        session_mod.reset_session()
        info = project_mod.open_project(three_box_model)
        assert info["model_count"] == 1

        assert model_mod.list_models()["count"] == 1
        assert function_mod.list_functions()["count"] == 4
        assert arrow_mod.list_arrows()["count"] == 4
        classifier_mod.list_classifiers()

        out = os.path.join(tmp_dir, "review.png")
        export_mod.export_diagram(out, overwrite=True)
        artifact("review render", out)
        assert export_mod.verify_output(out, "png")["valid"]

    def test_multi_model_project(self, tmp_dir):
        """One project carrying several notations and reference lists."""
        path = os.path.join(tmp_dir, "multi.rsf")
        project_mod.new_project(path, model_name="Process", diagram_type="idef0", overwrite=True)
        model_mod.create_model("Data flow", "dfd")

        function_mod.add_function("Register", model="Process")
        function_mod.add_function("Approve", model="Process")
        function_mod.add_function("Validate input", model="Data flow")
        function_mod.add_function("Store record", model="Data flow")

        classifier_mod.create_classifier("Roles")
        staff = classifier_mod.add_element("Roles", "Staff")
        classifier_mod.add_element("Roles", "Approver", parent=str(staff["id"]))
        classifier_mod.create_classifier("Documents")
        classifier_mod.add_element("Documents", "Application form")
        project_mod.save_project()

        assert model_mod.model_info("Process")["diagram_type"] == "idef0"
        assert model_mod.model_info("Data flow")["diagram_type"] == "dfd"
        assert function_mod.list_functions(model="Process")["count"] == 3
        assert function_mod.list_functions(model="Data flow")["count"] == 3

        model_id = model_mod.model_info("Data flow")["id"]
        assert model_mod.model_info(str(model_id))["name"] == "Data flow"

        for name in ("Process", "Data flow"):
            out = os.path.join(tmp_dir, f"{name.replace(' ', '-')}.png")
            export_mod.export_diagram(out, model=name, overwrite=True)
            artifact(name, out)
            assert export_mod.verify_output(out, "png")["valid"]

    def test_heavy_undo_stress(self, tmp_dir):
        """Backing out of a wrong direction, then partly redoing it."""
        path = os.path.join(tmp_dir, "stress.rsf")
        project_mod.new_project(path, model_name="Stress", overwrite=True)

        for i in range(12):
            function_mod.add_function(f"Step {i:02d}")
        project_mod.save_project()
        assert function_mod.list_functions(recursive=False)["count"] == 12

        session = session_mod.get_session()
        for _ in range(8):
            session.undo()
        assert function_mod.list_functions(recursive=False)["count"] == 4

        for _ in range(4):
            session.redo()
        assert function_mod.list_functions(recursive=False)["count"] == 8

        session_mod.reset_session()
        project_mod.open_project(path)
        assert function_mod.list_functions(recursive=False)["count"] == 8, \
            "the file on disk did not match the reported state"


# =================================================== CLI subprocess E2E


class TestCLISubprocess:
    """Drive the installed command exactly as a user or an agent would.

    No ``cwd`` is set anywhere here: an installed command must work from any
    directory.
    """

    CLI_BASE = _resolve_cli("cli-anything-ramus")

    def _run(self, args, check=True):
        return subprocess.run(
            self.CLI_BASE + args, capture_output=True, text=True, check=check
        )

    def _json(self, args):
        result = self._run(args)
        return json.loads(result.stdout)

    def test_help(self):
        result = self._run(["--help"])
        assert result.returncode == 0
        assert "project" in result.stdout

    def test_version(self):
        result = self._run(["--version"])
        assert result.returncode == 0
        assert "1.0.0" in result.stdout

    def test_doctor_reports_the_backend(self):
        data = self._json(["--json", "doctor"])
        assert data["available"] is True
        assert data["ramus_jar"].endswith(".jar")

    def test_project_new_json(self, tmp_dir):
        out = os.path.join(tmp_dir, "cli.rsf")
        data = self._json(["--json", "project", "new", out, "--model-name", "CLI model"])
        artifact("project", data["path"])
        assert data["created"] is True
        assert data["path"] == out
        assert os.path.isfile(out)
        with open(out, "rb") as handle:
            assert handle.read(4) == b"PK\x03\x04"

    def test_full_workflow_through_the_installed_command(self, tmp_dir):
        proj = os.path.join(tmp_dir, "workflow.rsf")
        png = os.path.join(tmp_dir, "workflow.png")
        pdf = os.path.join(tmp_dir, "workflow.pdf")

        self._run(["project", "new", proj, "--model-name", "Handle claim", "--author", "CLI"])
        for name in ("Register claim", "Assess claim", "Settle claim"):
            self._run(["--project", proj, "function", "add", name])
        self._run(["--project", proj, "arrow", "add", "--from", "border",
                   "--from-side", "input", "--to", "Register claim", "--name", "Claim form"])
        self._run(["--project", proj, "arrow", "add", "--from", "Register claim",
                   "--to", "Assess claim", "--name", "Registered claim"])
        self._run(["--project", proj, "arrow", "add", "--from", "Assess claim",
                   "--to", "Settle claim", "--name", "Assessment"])
        self._run(["--project", proj, "arrow", "add", "--from", "Settle claim",
                   "--to", "border", "--to-side", "output", "--name", "Payment"])
        self._run(["--project", proj, "function", "decompose", "Assess claim",
                   "Check cover", "Estimate value"])

        tree = self._json(["--json", "--project", proj, "model", "tree"])
        assert [c["node"] for c in tree["root"]["children"]] == ["A1", "A2", "A3"]
        assert [c["node"] for c in tree["root"]["children"][1]["children"]] == ["A21", "A22"]

        arrows = self._json(["--json", "--project", proj, "arrow", "list", "--diagram", "A0"])
        assert arrows["count"] == 4

        rendered = self._json(["--json", "--project", proj, "export", "diagram", png,
                               "--overwrite"])
        artifact("PNG", rendered["output"])
        assert rendered["verified"] is True
        assert export_mod.verify_output(png, "png")["valid"]
        assert pixel_stats(png)["ink_fraction"] > 0.005

        pdf_result = self._json(["--json", "--project", proj, "export", "pdf", pdf, "--overwrite"])
        artifact("PDF", pdf_result["output"])
        assert pdf_result["page_count"] == 2
        with open(pdf, "rb") as handle:
            assert handle.read(5) == b"%PDF-"

    def test_auto_save_makes_changes_visible_to_the_next_process(self, tmp_dir):
        proj = os.path.join(tmp_dir, "autosave.rsf")
        self._run(["project", "new", proj, "--model-name", "Autosave"])
        self._run(["--project", proj, "function", "add", "Persisted"])
        listing = self._json(["--json", "--project", proj, "function", "list", "--direct"])
        assert [f["name"] for f in listing["functions"]] == ["Persisted"]

    def test_dry_run_leaves_the_file_untouched(self, tmp_dir):
        proj = os.path.join(tmp_dir, "dryrun.rsf")
        self._run(["project", "new", proj, "--model-name", "Dry run"])
        self._run(["--project", proj, "function", "add", "Real box"])
        with open(proj, "rb") as handle:
            before = handle.read()

        self._run(["--dry-run", "--project", proj, "function", "add", "Ghost box"])
        with open(proj, "rb") as handle:
            after = handle.read()
        assert before == after, "--dry-run wrote to the project file"

        listing = self._json(["--json", "--project", proj, "function", "list", "--direct"])
        assert [f["name"] for f in listing["functions"]] == ["Real box"]

    def test_bad_argument_exits_non_zero_with_a_json_error(self, tmp_dir):
        proj = os.path.join(tmp_dir, "err.rsf")
        self._run(["project", "new", proj])
        result = self._run(["--json", "--project", proj, "function", "info", "Nope"], check=False)
        assert result.returncode != 0
        payload = json.loads(result.stderr)
        assert payload["ok"] is False
        assert "No function" in payload["error"]

    def test_missing_project_is_reported_clearly(self, tmp_dir):
        result = self._run(
            ["--project", os.path.join(tmp_dir, "nothing.rsf"), "model", "list"], check=False
        )
        assert result.returncode != 0
        assert "not found" in (result.stdout + result.stderr).lower()

    def test_session_status_json(self, tmp_dir):
        proj = os.path.join(tmp_dir, "status.rsf")
        self._run(["project", "new", proj, "--model-name", "Status"])
        self._run(["--project", proj, "function", "add", "One"])
        data = self._json(["--json", "--project", proj, "session", "status"])
        assert data["project_open"] is True
        assert data["undo_available"] >= 1

    def test_preview_capture_through_the_cli(self, tmp_dir):
        proj = os.path.join(tmp_dir, "preview.rsf")
        root = os.path.join(tmp_dir, "bundles")
        self._run(["project", "new", proj, "--model-name", "Preview"])
        self._run(["--project", proj, "function", "add", "One"])
        self._run(["--project", proj, "function", "add", "Two"])
        data = self._json(["--json", "--project", proj, "preview", "capture", "--root-dir", root])
        artifact("bundle", data["_bundle_dir"])
        assert data["protocol_version"] == "preview-bundle/v1"
        assert os.path.isfile(data["_manifest_path"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
