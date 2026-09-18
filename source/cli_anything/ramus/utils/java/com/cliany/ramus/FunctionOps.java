package com.cliany.ramus;

import java.awt.Color;
import java.awt.Font;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.dsoft.pb.types.FRectangle;
import com.ramussoft.common.Qualifier;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;

/** Function (activity box) operations on a model's decomposition tree. */
final class FunctionOps {

    private FunctionOps() {
    }

    /**
     * Default box geometry. The Ramus drawing area is 800 x 444 model units, and
     * IDEF0 recommends three to six boxes per diagram, so boxes of this size
     * step down the classic diagonal without leaving the page for six children.
     */
    static final double DEFAULT_WIDTH = 112.0;
    static final double DEFAULT_HEIGHT = 62.0;
    private static final double STEP_X = 118.0;
    private static final double STEP_Y = 69.0;
    private static final double ORIGIN_X = 45.0;
    private static final double ORIGIN_Y = 22.0;
    private static final int STAIRCASE_SLOTS = 6;

    static Object dispatch(RamusBridge.Ops ops, String op, Map<String, Object> args) throws Exception {
        if ("function.list".equals(op)) {
            return list(ops, args);
        }
        if ("function.add".equals(op)) {
            return add(ops, args);
        }
        if ("function.info".equals(op)) {
            return info(ops, args);
        }
        if ("function.rename".equals(op)) {
            return rename(ops, args);
        }
        if ("function.move".equals(op)) {
            return geometry(ops, args, true);
        }
        if ("function.resize".equals(op)) {
            return geometry(ops, args, false);
        }
        if ("function.set-color".equals(op)) {
            return setColor(ops, args);
        }
        if ("function.set-font".equals(op)) {
            return setFont(ops, args);
        }
        if ("function.set-type".equals(op)) {
            return setType(ops, args);
        }
        if ("function.delete".equals(op)) {
            return delete(ops, args);
        }
        throw new IllegalArgumentException("Unknown operation: " + op);
    }

    // ------------------------------------------------------------ describe

    static Map<String, Object> describe(DataPlugin dp, Function f) {
        Map<String, Object> m = Json.obj();
        m.put("id", Long.valueOf(Resolve.elementId(f)));
        m.put("node", Resolve.node(dp, f));
        m.put("name", f.getName());
        m.put("type", typeName(f.getType()));
        m.put("type_code", Integer.valueOf(f.getType()));
        FRectangle b = f.getBounds();
        Map<String, Object> bounds = Json.obj();
        bounds.put("x", Double.valueOf(round(b.getX())));
        bounds.put("y", Double.valueOf(round(b.getY())));
        bounds.put("width", Double.valueOf(round(b.getWidth())));
        bounds.put("height", Double.valueOf(round(b.getHeight())));
        m.put("bounds", bounds);
        m.put("background", toHex(f.getBackground()));
        m.put("foreground", toHex(f.getForeground()));
        Font font = f.getFont();
        if (font != null) {
            Map<String, Object> fm = Json.obj();
            fm.put("family", font.getFamily());
            fm.put("size", Integer.valueOf(font.getSize()));
            fm.put("bold", Boolean.valueOf(font.isBold()));
            fm.put("italic", Boolean.valueOf(font.isItalic()));
            m.put("font", fm);
        }
        List<Function> children = Resolve.children(dp, f);
        m.put("child_count", Integer.valueOf(children.size()));
        m.put("decomposed", Boolean.valueOf(f.isHaveRealChilds()));
        Function parent = f.getParentRow() instanceof Function ? (Function) f.getParentRow() : null;
        m.put("parent_id", parent == null ? null : Long.valueOf(Resolve.elementId(parent)));
        m.put("parent_name", parent == null ? null : parent.getName());
        return m;
    }

    private static double round(double value) {
        return Math.round(value * 100.0) / 100.0;
    }

    static String toHex(Color c) {
        if (c == null) {
            return null;
        }
        return String.format("#%02x%02x%02x", Integer.valueOf(c.getRed()),
                Integer.valueOf(c.getGreen()), Integer.valueOf(c.getBlue()));
    }

    static Color parseColor(String value, String argName) {
        if (value == null) {
            return null;
        }
        String v = value.trim();
        if (v.length() == 0) {
            return null;
        }
        if (v.startsWith("#")) {
            v = v.substring(1);
        }
        if (v.length() == 3) {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 3; i++) {
                sb.append(v.charAt(i)).append(v.charAt(i));
            }
            v = sb.toString();
        }
        if (v.length() != 6) {
            throw new IllegalArgumentException(
                    "Invalid colour for " + argName + ": '" + value + "'. Use #rrggbb");
        }
        try {
            return new Color(Integer.parseInt(v, 16));
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException(
                    "Invalid colour for " + argName + ": '" + value + "'. Use #rrggbb");
        }
    }

    static String typeName(int type) {
        switch (type) {
            case Function.TYPE_PROCESS_KOMPLEX:
                return "complex";
            case Function.TYPE_PROCESS:
                return "process";
            case Function.TYPE_PROCESS_PART:
                return "subprocess";
            case Function.TYPE_OPERATION:
                return "operation";
            case Function.TYPE_ACTION:
                return "action";
            case Function.TYPE_EXTERNAL_REFERENCE:
                return "external";
            case Function.TYPE_DATA_STORE:
                return "datastore";
            case Function.TYPE_DFDS_ROLE:
                return "role";
            default:
                return "type" + type;
        }
    }

    static int parseType(String value) {
        if (value == null || value.trim().length() == 0) {
            return Function.TYPE_PROCESS_KOMPLEX;
        }
        String v = value.trim().toLowerCase();
        if ("complex".equals(v)) {
            return Function.TYPE_PROCESS_KOMPLEX;
        }
        if ("process".equals(v)) {
            return Function.TYPE_PROCESS;
        }
        if ("subprocess".equals(v)) {
            return Function.TYPE_PROCESS_PART;
        }
        if ("operation".equals(v)) {
            return Function.TYPE_OPERATION;
        }
        if ("action".equals(v)) {
            return Function.TYPE_ACTION;
        }
        if ("external".equals(v)) {
            return Function.TYPE_EXTERNAL_REFERENCE;
        }
        if ("datastore".equals(v)) {
            return Function.TYPE_DATA_STORE;
        }
        if ("role".equals(v)) {
            return Function.TYPE_DFDS_ROLE;
        }
        throw new IllegalArgumentException("Unknown function type '" + value
                + "'. Use one of: complex, process, subprocess, operation, action, external, datastore, role");
    }

    // ---------------------------------------------------------------- list

    static Map<String, Object> list(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        String parentSelector = Json.str(args, "parent", null);
        boolean recursive = Json.bool(args, "recursive", parentSelector == null);

        List<Function> functions;
        if (parentSelector == null) {
            functions = recursive ? Resolve.allFunctions(dp) : Resolve.children(dp, dp.getBaseFunction());
        } else {
            Function parent = Resolve.function(dp, parentSelector, "parent");
            if (recursive) {
                functions = new ArrayList<Function>();
                collectRecursive(dp, parent, functions);
            } else {
                functions = Resolve.children(dp, parent);
            }
        }

        List<Object> out = new ArrayList<Object>();
        for (Function f : functions) {
            out.add(describe(dp, f));
        }
        Map<String, Object> m = Json.obj();
        m.put("model", q.getName());
        m.put("model_id", Long.valueOf(q.getId()));
        m.put("functions", out);
        m.put("count", Integer.valueOf(out.size()));
        return m;
    }

    private static void collectRecursive(DataPlugin dp, Function parent, List<Function> out) {
        for (Function child : Resolve.children(dp, parent)) {
            out.add(child);
            collectRecursive(dp, child, out);
        }
    }

    // ----------------------------------------------------------------- add

    static Map<String, Object> add(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        final Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        String parentSelector = Json.str(args, "parent", null);
        final Function parent = parentSelector == null
                ? dp.getBaseFunction()
                : Resolve.function(dp, parentSelector, "parent");
        final String name = Json.reqStr(args, "name");
        final int type = parseType(Json.str(args, "type", null));

        // Lay boxes out on the IDEF0 diagonal unless the caller places them.
        // Past six siblings the staircase wraps; those diagrams want explicit
        // --x/--y anyway, and IDEF0 advises splitting them up.
        int slot = Resolve.children(dp, parent).size() % STAIRCASE_SLOTS;
        final double width = Json.dbl(args, "width", DEFAULT_WIDTH);
        final double height = Json.dbl(args, "height", DEFAULT_HEIGHT);
        final double x = Json.dbl(args, "x", ORIGIN_X + slot * STEP_X);
        final double y = Json.dbl(args, "y", ORIGIN_Y + slot * STEP_Y);

        Function created = ops.inTransaction(new RamusBridge.Task<Function>() {
            public Function run() {
                Function f = dp.createFunction(parent, type);
                f.setName(name);
                f.setBounds(new FRectangle(x, y, width, height));
                return f;
            }
        });
        Map<String, Object> m = describe(dp, created);
        m.put("model", q.getName());
        m.put("created", Boolean.TRUE);
        return m;
    }

    // ---------------------------------------------------------------- info

    static Map<String, Object> info(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        Map<String, Object> m = describe(dp, f);
        m.put("model", q.getName());
        List<Object> children = new ArrayList<Object>();
        for (Function child : Resolve.children(dp, f)) {
            Map<String, Object> cm = Json.obj();
            cm.put("id", Long.valueOf(Resolve.elementId(child)));
            cm.put("node", Resolve.node(dp, child));
            cm.put("name", child.getName());
            children.add(cm);
        }
        m.put("children", children);
        m.put("arrows_on_own_diagram", Integer.valueOf(Resolve.sectorsOf(dp, f).size()));
        return m;
    }

    // -------------------------------------------------------------- mutate

    static Map<String, Object> rename(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        final String name = Json.reqStr(args, "name");
        final String old = f.getName();
        final boolean isBase = Resolve.sameRow(f, dp.getBaseFunction());
        final Qualifier model = q;
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                if (isBase) {
                    // The base function's name is the model qualifier's name.
                    model.setName(name);
                    ops.engine.updateQualifier(model);
                } else {
                    f.setName(name);
                }
                return null;
            }
        });
        Map<String, Object> m = describe(dp, f);
        m.put("previous_name", old);
        if (isBase) {
            m.put("name", name);
            m.put("renamed_model", Boolean.TRUE);
        }
        return m;
    }

    static Map<String, Object> geometry(final RamusBridge.Ops ops, Map<String, Object> args,
                                        boolean move) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        FRectangle current = f.getBounds();
        final double x = Json.dbl(args, "x", current.getX());
        final double y = Json.dbl(args, "y", current.getY());
        final double width = Json.dbl(args, "width", current.getWidth());
        final double height = Json.dbl(args, "height", current.getHeight());
        if (width <= 0 || height <= 0) {
            throw new IllegalArgumentException("Width and height must be positive");
        }
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                f.setBounds(new FRectangle(x, y, width, height));
                return null;
            }
        });
        return describe(dp, f);
    }

    static Map<String, Object> setColor(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        final Color background = parseColor(Json.str(args, "background", null), "background");
        final Color foreground = parseColor(Json.str(args, "foreground", null), "foreground");
        if (background == null && foreground == null) {
            throw new IllegalArgumentException("Pass --background and/or --foreground");
        }
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                if (background != null) {
                    f.setBackground(background);
                }
                if (foreground != null) {
                    f.setForeground(foreground);
                }
                return null;
            }
        });
        return describe(dp, f);
    }

    static Map<String, Object> setFont(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        Font current = f.getFont();
        if (current == null) {
            current = new Font("Dialog", Font.PLAIN, 10);
        }
        final String family = Json.str(args, "family", current.getFamily());
        final int size = Json.integer(args, "size", current.getSize());
        int style = current.getStyle();
        if (args.containsKey("bold") || args.containsKey("italic")) {
            boolean bold = Json.bool(args, "bold", current.isBold());
            boolean italic = Json.bool(args, "italic", current.isItalic());
            style = (bold ? Font.BOLD : 0) | (italic ? Font.ITALIC : 0);
        }
        if (size <= 0) {
            throw new IllegalArgumentException("Font size must be positive");
        }
        final int finalStyle = style;
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                f.setFont(new Font(family, finalStyle, size));
                return null;
            }
        });
        return describe(dp, f);
    }

    static Map<String, Object> setType(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        final int type = parseType(Json.reqStr(args, "type"));
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                f.setType(type);
                return null;
            }
        });
        return describe(dp, f);
    }

    static Map<String, Object> delete(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function f = Resolve.function(dp, Json.reqStr(args, "function"), "function");
        if (Resolve.sameRow(f, dp.getBaseFunction())) {
            throw new IllegalArgumentException(
                    "The base function (A0) cannot be deleted; delete the model instead");
        }
        final long id = Resolve.elementId(f);
        final String name = f.getName();
        final String node = Resolve.node(dp, f);
        Boolean removed = ops.inTransaction(new RamusBridge.Task<Boolean>() {
            public Boolean run() {
                return Boolean.valueOf(dp.removeRow(f));
            }
        });
        Map<String, Object> m = Json.obj();
        m.put("deleted", removed);
        m.put("id", Long.valueOf(id));
        m.put("node", node);
        m.put("name", name);
        return m;
    }
}
