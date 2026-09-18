package com.cliany.ramus;

import java.awt.Dimension;
import java.awt.Graphics2D;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.itextpdf.awt.DefaultFontMapper;
import com.itextpdf.awt.PdfGraphics2D;
import com.itextpdf.text.Document;
import com.itextpdf.text.Rectangle;
import com.itextpdf.text.pdf.PdfContentByte;
import com.itextpdf.text.pdf.PdfWriter;
import com.ramussoft.common.Attribute;
import com.ramussoft.common.Qualifier;
import com.ramussoft.idef0.IDEF0Plugin;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;
import com.ramussoft.pb.print.PIDEF0painter;

/**
 * Rendering and interchange, all of it performed by Ramus itself.
 *
 * <p>Raster and vector output go through {@link PIDEF0painter}, the same
 * painter the Ramus GUI uses for its own image export and printing. PDF wraps
 * that painter in iText's {@code PdfGraphics2D}, mirroring the print-to-pdf
 * plugin. IDL import/export calls the engine's own IDL codec.
 */
final class ExportOps {

    private ExportOps() {
    }

    static final int DEFAULT_WIDTH = 1600;
    static final int DEFAULT_HEIGHT = 1200;

    static Object dispatch(RamusBridge.Ops ops, String op, Map<String, Object> args) throws Exception {
        if ("export.formats".equals(op)) {
            return formats();
        }
        if ("export.diagram".equals(op)) {
            return diagram(ops, args);
        }
        if ("export.all".equals(op)) {
            return all(ops, args);
        }
        if ("export.pdf".equals(op)) {
            return pdf(ops, args);
        }
        if ("export.idl".equals(op)) {
            return idl(ops, args);
        }
        if ("import.idl".equals(op)) {
            return importIdl(ops, args);
        }
        throw new IllegalArgumentException("Unknown operation: " + op);
    }

    static Map<String, Object> formats() {
        Map<String, Object> m = Json.obj();
        List<Object> raster = new ArrayList<Object>();
        raster.add("png");
        raster.add("jpg");
        raster.add("bmp");
        List<Object> vector = new ArrayList<Object>();
        vector.add("svg");
        vector.add("pdf");
        List<Object> interchange = new ArrayList<Object>();
        interchange.add("idl");
        List<Object> displayOnly = new ArrayList<Object>();
        displayOnly.add("emf");
        m.put("raster", raster);
        m.put("vector", vector);
        m.put("interchange", interchange);
        m.put("needs_display", displayOnly);
        m.put("needs_display_note",
                "Ramus writes EMF through FreeHEP, which asks the toolkit for the screen size."
                        + " That call cannot be answered headlessly, so EMF needs a real display"
                        + " and CLI_ANYTHING_RAMUS_HEADLESS=0.");
        m.put("headless", Boolean.valueOf(java.awt.GraphicsEnvironment.isHeadless()));
        m.put("renderer", "com.ramussoft.pb.print.PIDEF0painter (Ramus)");
        return m;
    }

    static int formatCode(String format) {
        String f = format == null ? "png" : format.trim().toLowerCase();
        if ("png".equals(f)) {
            return PIDEF0painter.PNG_FORMAT;
        }
        if ("jpg".equals(f) || "jpeg".equals(f)) {
            return PIDEF0painter.JPEG_FORMAT;
        }
        if ("bmp".equals(f)) {
            return PIDEF0painter.BMP_FORMAT;
        }
        if ("svg".equals(f)) {
            return PIDEF0painter.SVG_FORMAT;
        }
        if ("emf".equals(f)) {
            return PIDEF0painter.EMF_FORMAT;
        }
        throw new IllegalArgumentException("Unknown image format '" + format
                + "'. Use one of: png, jpg, bmp, svg, emf (or the 'export pdf' command)");
    }

    /** Diagrams that can actually be rendered: functions that were decomposed. */
    static List<Function> diagrams(DataPlugin dp) {
        List<Function> result = new ArrayList<Function>();
        for (Function f : Resolve.allFunctions(dp)) {
            if (f.isHaveRealChilds()) {
                result.add(f);
            }
        }
        return result;
    }

    static Map<String, Object> diagram(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        String selector = Json.str(args, "diagram", null);
        Function function = selector == null
                ? dp.getBaseFunction()
                : Resolve.function(dp, selector, "diagram");

        File target = RamusBridge.resolve(Json.reqStr(args, "path"));
        String format = Json.str(args, "format", formatFromExtension(target, "png"));
        boolean overwrite = Json.bool(args, "overwrite", false);
        int width = Json.integer(args, "width", DEFAULT_WIDTH);
        int height = Json.integer(args, "height", DEFAULT_HEIGHT);

        if (target.exists() && !overwrite) {
            throw new IllegalStateException(
                    "File already exists: " + target.getAbsolutePath() + " (pass --overwrite to replace it)");
        }
        requireDecomposed(dp, function);

        Map<String, Object> written = render(dp, function, target, format, width, height);
        written.put("model", q.getName());
        written.put("diagram", function.getName());
        written.put("diagram_node", Resolve.node(dp, function));
        return written;
    }

    private static void requireDecomposed(DataPlugin dp, Function function) {
        if (!function.isHaveRealChilds()) {
            throw new IllegalStateException("Function '" + function.getName() + "' ("
                    + Resolve.node(dp, function)
                    + ") has no child boxes, so it has no diagram to render."
                    + " Add children with 'function add --parent " + Resolve.node(dp, function) + "'.");
        }
    }

    static Map<String, Object> render(DataPlugin dp, Function function, File target,
                                      String format, int width, int height) throws Exception {
        int code = formatCode(format);
        mkdirs(target);
        PIDEF0painter painter = new PIDEF0painter(function, new Dimension(width, height), dp);
        FileOutputStream out = new FileOutputStream(target);
        try {
            painter.writeToStream(out, code);
        } catch (java.awt.HeadlessException e) {
            throw new IllegalStateException(
                    "EMF export needs a graphics display. The EMF writer Ramus uses (FreeHEP) asks the"
                            + " toolkit for the screen size while writing its header, which no headless JVM"
                            + " can answer. Export png, jpg, bmp, svg or pdf instead, or run with a display"
                            + " and CLI_ANYTHING_RAMUS_HEADLESS=0.", e);
        } finally {
            out.close();
        }
        Map<String, Object> m = Json.obj();
        m.put("output", target.getAbsolutePath());
        m.put("format", format.toLowerCase());
        m.put("file_size", Long.valueOf(target.length()));
        m.put("requested_width", Integer.valueOf(width));
        m.put("requested_height", Integer.valueOf(height));
        m.put("renderer", "PIDEF0painter");
        return m;
    }

    static Map<String, Object> all(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        File dir = RamusBridge.resolve(Json.reqStr(args, "dir"));
        String format = Json.str(args, "format", "png");
        int width = Json.integer(args, "width", DEFAULT_WIDTH);
        int height = Json.integer(args, "height", DEFAULT_HEIGHT);
        boolean overwrite = Json.bool(args, "overwrite", false);

        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new java.io.IOException("Cannot create directory: " + dir.getAbsolutePath());
        }
        List<Function> targets = diagrams(dp);
        if (targets.isEmpty()) {
            throw new IllegalStateException("Model '" + q.getName()
                    + "' has no decomposed function, so there is nothing to render");
        }

        List<Object> outputs = new ArrayList<Object>();
        for (Function f : targets) {
            String node = Resolve.node(dp, f);
            File target = new File(dir, node + "-" + slug(f.getName()) + "." + format.toLowerCase());
            if (target.exists() && !overwrite) {
                throw new IllegalStateException("File already exists: " + target.getAbsolutePath()
                        + " (pass --overwrite to replace it)");
            }
            Map<String, Object> written = render(dp, f, target, format, width, height);
            written.put("diagram", f.getName());
            written.put("diagram_node", node);
            outputs.add(written);
        }
        Map<String, Object> m = Json.obj();
        m.put("model", q.getName());
        m.put("directory", dir.getAbsolutePath());
        m.put("format", format.toLowerCase());
        m.put("outputs", outputs);
        m.put("count", Integer.valueOf(outputs.size()));
        return m;
    }

    /**
     * One PDF page per decomposed diagram, painted by Ramus's own painter onto
     * an iText graphics context.
     */
    static Map<String, Object> pdf(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        File target = RamusBridge.resolve(Json.reqStr(args, "path"));
        boolean overwrite = Json.bool(args, "overwrite", false);
        if (target.exists() && !overwrite) {
            throw new IllegalStateException(
                    "File already exists: " + target.getAbsolutePath() + " (pass --overwrite to replace it)");
        }
        int width = Json.integer(args, "width", 1190);
        int height = Json.integer(args, "height", 842);

        String selector = Json.str(args, "diagram", null);
        List<Function> targets;
        if (selector == null) {
            targets = diagrams(dp);
        } else {
            Function f = Resolve.function(dp, selector, "diagram");
            requireDecomposed(dp, f);
            targets = new ArrayList<Function>();
            targets.add(f);
        }
        if (targets.isEmpty()) {
            throw new IllegalStateException("Model '" + q.getName()
                    + "' has no decomposed function, so there is nothing to render");
        }

        mkdirs(target);
        Document document = new Document(new Rectangle(width, height));
        FileOutputStream out = new FileOutputStream(target);
        List<Object> pages = new ArrayList<Object>();
        try {
            PdfWriter writer = PdfWriter.getInstance(document, out);
            document.open();
            PdfContentByte cb = writer.getDirectContent();
            DefaultFontMapper mapper = new DefaultFontMapper();
            for (int i = 0; i < targets.size(); i++) {
                Function f = targets.get(i);
                if (i > 0) {
                    document.newPage();
                }
                PIDEF0painter painter = new PIDEF0painter(f, new Dimension(width, height), dp);
                painter.getMovingArea().setNativePaint(true);
                Graphics2D g = new PdfGraphics2D(cb, width, height, mapper);
                try {
                    painter.paint(g, 0, 0);
                } finally {
                    g.dispose();
                }
                Map<String, Object> pm = Json.obj();
                pm.put("page", Integer.valueOf(i + 1));
                pm.put("diagram", f.getName());
                pm.put("diagram_node", Resolve.node(dp, f));
                pages.add(pm);
            }
            document.close();
        } finally {
            out.close();
        }

        Map<String, Object> m = Json.obj();
        m.put("output", target.getAbsolutePath());
        m.put("format", "pdf");
        m.put("file_size", Long.valueOf(target.length()));
        m.put("model", q.getName());
        m.put("pages", pages);
        m.put("page_count", Integer.valueOf(pages.size()));
        m.put("renderer", "PIDEF0painter + iText PdfGraphics2D");
        return m;
    }

    // ------------------------------------------------------------------ IDL

    static Map<String, Object> idl(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        File target = RamusBridge.resolve(Json.reqStr(args, "path"));
        boolean overwrite = Json.bool(args, "overwrite", false);
        String encoding = Json.str(args, "encoding", "UTF-8");
        if (target.exists() && !overwrite) {
            throw new IllegalStateException(
                    "File already exists: " + target.getAbsolutePath() + " (pass --overwrite to replace it)");
        }
        mkdirs(target);
        OutputStream out = new FileOutputStream(target);
        try {
            dp.exportToIDL(dp.getBaseFunction(), out, encoding);
        } catch (NullPointerException e) {
            if (isIdlLabelDefect(e)) {
                throw new IllegalStateException(
                        "Ramus cannot export this model to IDL: its IDL writer crashes on arrows that carry a"
                                + " visible label. This is a defect in Ramus itself"
                                + " (IDLExporter.printSegments passes null to PStringBounder, which then"
                                + " dereferences it), not in the CLI, and the Ramus GUI fails the same way."
                                + " Export to png/svg/pdf instead, or hide the arrow labels first.", e);
            }
            throw e;
        } finally {
            out.close();
        }
        Map<String, Object> m = Json.obj();
        m.put("output", target.getAbsolutePath());
        m.put("format", "idl");
        m.put("encoding", encoding);
        m.put("file_size", Long.valueOf(target.length()));
        m.put("model", q.getName());
        return m;
    }

    /** Recognises the known upstream failure in Ramus's IDL context-diagram lookup. */
    private static boolean isIdlContextNodeDefect(ArrayIndexOutOfBoundsException e) {
        for (StackTraceElement frame : e.getStackTrace()) {
            if ("com.ramussoft.pb.data.negine.IDLImporter".equals(frame.getClassName())
                    && "getFunction".equals(frame.getMethodName())) {
                return true;
            }
        }
        return false;
    }

    /** Recognises the known upstream NPE in Ramus's IDL label writer. */
    private static boolean isIdlLabelDefect(NullPointerException e) {
        for (StackTraceElement frame : e.getStackTrace()) {
            if ("com.ramussoft.pb.print.PStringBounder".equals(frame.getClassName())) {
                return true;
            }
        }
        return false;
    }

    static Map<String, Object> importIdl(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final File source = RamusBridge.resolve(Json.reqStr(args, "path"));
        final String encoding = Json.str(args, "encoding", "cp1251");
        final String name = Json.str(args, "name", stripExtension(source.getName()));
        for (Qualifier q : Resolve.models(ops.engine)) {
            if (name.equals(q.getName())) {
                throw new IllegalStateException(
                        "A model named '" + name + "' already exists; pass --name to import under a different name");
            }
        }

        Qualifier model = ops.inTransaction(new RamusBridge.Task<Qualifier>() {
            public Qualifier run() throws Exception {
                Attribute nameAttribute = ops.nameAttribute();
                Qualifier q = ops.engine.createQualifier();
                q.setName(name);
                q.getAttributes().add(nameAttribute);
                q.setAttributeForName(nameAttribute.getId());
                IDEF0Plugin.installFunctionAttributes(q, ops.engine);
                ops.engine.updateQualifier(q);

                DataPlugin dp = Resolve.plugin(ops, q);
                InputStream in = RamusBridge.openRead(source);
                try {
                    dp.importFromIDL(dp, encoding, in);
                } catch (ArrayIndexOutOfBoundsException e) {
                    if (isIdlContextNodeDefect(e)) {
                        throw new IllegalStateException(
                                "Ramus could not import this IDL file. Its importer expects the first"
                                        + " 'DIAGRAM GRAPHIC' section to be the IDEF0 context diagram named"
                                        + " A-0, and this file names it something else. Ramus's own IDL"
                                        + " exporter writes 'A0' there, so Ramus cannot re-import a file it"
                                        + " exported without that line being changed to"
                                        + " 'DIAGRAM GRAPHIC A-0 ;'. This is a mismatch inside Ramus"
                                        + " between its IDL writer and its IDL reader.", e);
                    }
                    throw e;
                } finally {
                    in.close();
                }
                ProjectOps.registerInModelTree(ops.engine, q);
                return q;
            }
        });

        Map<String, Object> m = ModelOps.describe(ops, ops.engine.getQualifier(model.getId()), true);
        m.put("imported", Boolean.TRUE);
        m.put("source", source.getAbsolutePath());
        m.put("encoding", encoding);
        return m;
    }

    // -------------------------------------------------------------- helpers

    static String formatFromExtension(File file, String fallback) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        if (dot < 0 || dot == name.length() - 1) {
            return fallback;
        }
        return name.substring(dot + 1).toLowerCase();
    }

    static String stripExtension(String name) {
        int dot = name.lastIndexOf('.');
        return dot <= 0 ? name : name.substring(0, dot);
    }

    /** Filename-safe form of a diagram name, for batch export. */
    static String slug(String name) {
        if (name == null || name.trim().length() == 0) {
            return "diagram";
        }
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < name.length() && sb.length() < 48; i++) {
            char c = name.charAt(i);
            if (Character.isLetterOrDigit(c) && c < 128) {
                sb.append(Character.toLowerCase(c));
            } else if (sb.length() > 0 && sb.charAt(sb.length() - 1) != '-') {
                sb.append('-');
            }
        }
        while (sb.length() > 0 && sb.charAt(sb.length() - 1) == '-') {
            sb.setLength(sb.length() - 1);
        }
        return sb.length() == 0 ? "diagram" : sb.toString();
    }

    private static void mkdirs(File target) throws java.io.IOException {
        File parent = target.getAbsoluteFile().getParentFile();
        if (parent != null && !parent.isDirectory() && !parent.mkdirs()) {
            throw new java.io.IOException("Cannot create directory: " + parent.getAbsolutePath());
        }
    }
}
