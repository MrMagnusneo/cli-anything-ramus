package com.cliany.ramus;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Vector;

import com.ramussoft.common.Engine;
import com.ramussoft.common.Qualifier;
import com.ramussoft.idef0.IDEF0Plugin;
import com.ramussoft.idef0.NDataPluginFactory;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;
import com.ramussoft.pb.Row;
import com.ramussoft.pb.Sector;
import com.ramussoft.pb.idef.visual.MovingPanel;
import com.ramussoft.pb.types.GlobalId;

/** Turns the CLI's user-facing selectors into live Ramus objects. */
final class Resolve {

    private Resolve() {
    }

    // ------------------------------------------------------------- models

    static List<Qualifier> models(Engine engine) {
        List<Qualifier> all = IDEF0Plugin.getBaseQualifiers(engine);
        List<Qualifier> result = new ArrayList<Qualifier>();
        for (Qualifier q : all) {
            // F_BASE_FUNCTIONS is the plugin's internal holder, not a user model.
            if (!IDEF0Plugin.F_BASE_FUNCTIONS.equals(q.getName())) {
                result.add(q);
            }
        }
        return result;
    }

    /**
     * Resolves the {@code model} argument: a numeric qualifier id or a model
     * name. When omitted, the single model in the project is used.
     */
    static Qualifier model(RamusBridge.Ops ops, Map<String, Object> args) {
        ops.requireOpen();
        List<Qualifier> all = models(ops.engine);
        String raw = Json.str(args, "model", null);
        String selector = raw == null ? null : raw.trim();

        if (selector == null || selector.length() == 0) {
            if (all.size() == 1) {
                return all.get(0);
            }
            if (all.isEmpty()) {
                throw new IllegalStateException(
                        "This project contains no IDEF0/DFD model. Create one with: model create <name>");
            }
            StringBuilder sb = new StringBuilder(
                    "Project has " + all.size() + " models; pass --model. Available: ");
            for (int i = 0; i < all.size(); i++) {
                if (i > 0) {
                    sb.append(", ");
                }
                sb.append(all.get(i).getName()).append(" (id ").append(all.get(i).getId()).append(')');
            }
            throw new IllegalArgumentException(sb.toString());
        }

        for (Qualifier q : all) {
            if (selector.equals(Long.toString(q.getId()))) {
                return q;
            }
        }
        for (Qualifier q : all) {
            if (selector.equals(q.getName())) {
                return q;
            }
        }
        for (Qualifier q : all) {
            if (selector.equalsIgnoreCase(q.getName())) {
                return q;
            }
        }
        throw new IllegalArgumentException("No model named or numbered '" + selector + "'");
    }

    static DataPlugin plugin(RamusBridge.Ops ops, Qualifier model) {
        return NDataPluginFactory.getDataPlugin(model, ops.engine, ops.rules);
    }

    // ---------------------------------------------------------- functions

    /** All functions of a model, base function first, in tree order. */
    static List<Function> allFunctions(DataPlugin dp) {
        List<Function> result = new ArrayList<Function>();
        Function base = dp.getBaseFunction();
        result.add(base);
        collect(dp, base, result);
        return result;
    }

    private static void collect(DataPlugin dp, Function parent, List<Function> out) {
        Vector<Row> children = dp.getChilds(parent, true);
        for (Row row : children) {
            if (row instanceof Function) {
                Function f = (Function) row;
                out.add(f);
                collect(dp, f, out);
            }
        }
    }

    static List<Function> children(DataPlugin dp, Function parent) {
        List<Function> result = new ArrayList<Function>();
        for (Row row : dp.getChilds(parent, true)) {
            if (row instanceof Function) {
                result.add((Function) row);
            }
        }
        return result;
    }

    /**
     * Resolves a function selector: element id, IDEF0 node number (A0, A12),
     * or an exact / case-insensitive name.
     */
    static Function function(DataPlugin dp, String selector, String argName) {
        if (selector == null || selector.trim().length() == 0) {
            throw new IllegalArgumentException("Missing required argument: " + argName);
        }
        selector = selector.trim();
        List<Function> all = allFunctions(dp);

        for (Function f : all) {
            if (selector.equals(Long.toString(elementId(f)))) {
                return f;
            }
        }
        for (Function f : all) {
            if (selector.equalsIgnoreCase(node(dp, f))) {
                return f;
            }
        }
        for (Function f : all) {
            if (selector.equals(f.getName())) {
                return f;
            }
        }
        List<Function> insensitive = new ArrayList<Function>();
        for (Function f : all) {
            if (selector.equalsIgnoreCase(f.getName())) {
                insensitive.add(f);
            }
        }
        if (insensitive.size() == 1) {
            return insensitive.get(0);
        }
        if (insensitive.size() > 1) {
            throw new IllegalArgumentException(
                    "'" + selector + "' matches " + insensitive.size()
                            + " functions; use the numeric id from 'function list'");
        }
        throw new IllegalArgumentException("No function with id, node or name '" + selector + "'");
    }

    static long elementId(Row row) {
        return row.getElement() == null ? -1L : row.getElement().getId();
    }

    /** IDEF0 node number: base is A0, its children A1..An, then A11, A12... */
    static String node(DataPlugin dp, Function function) {
        Function base = dp.getBaseFunction();
        if (sameRow(function, base)) {
            return "A0";
        }
        List<Integer> indexes = new ArrayList<Integer>();
        Row current = function;
        while (current != null && !sameRow(current, base)) {
            Row parent = current.getParentRow();
            if (parent == null) {
                break;
            }
            int index = 1;
            for (Row sibling : dp.getChilds(parent, true)) {
                if (sameRow(sibling, current)) {
                    break;
                }
                index++;
            }
            indexes.add(0, Integer.valueOf(index));
            current = parent;
        }
        StringBuilder sb = new StringBuilder("A");
        for (Integer i : indexes) {
            sb.append(i);
        }
        return sb.toString();
    }

    static boolean sameRow(Row a, Row b) {
        if (a == null || b == null) {
            return a == b;
        }
        return elementId(a) == elementId(b);
    }

    // ------------------------------------------------------------ sectors

    /** Every arrow drawn on the diagram that decomposes {@code diagram}. */
    static List<Sector> sectorsOf(DataPlugin dp, Function diagram) {
        List<Sector> result = new ArrayList<Sector>();
        for (Object o : dp.getAllSectors()) {
            Sector s = (Sector) o;
            Function owner = s.getFunction();
            if (owner != null && sameRow(owner, diagram)) {
                result.add(s);
            }
        }
        return result;
    }

    static long sectorId(Sector s) {
        GlobalId gid = s.getGlobalId();
        return gid == null ? -1L : gid.getLocalId();
    }

    static Sector sector(DataPlugin dp, String selector) {
        if (selector == null || selector.trim().length() == 0) {
            throw new IllegalArgumentException("Missing required argument: id");
        }
        selector = selector.trim();
        List<Sector> matches = new ArrayList<Sector>();
        for (Object o : dp.getAllSectors()) {
            Sector s = (Sector) o;
            if (selector.equals(Long.toString(sectorId(s)))) {
                return s;
            }
            String name = s.getName();
            if (name != null && selector.equalsIgnoreCase(name)) {
                matches.add(s);
            }
        }
        if (matches.size() == 1) {
            return matches.get(0);
        }
        if (matches.size() > 1) {
            throw new IllegalArgumentException(
                    "'" + selector + "' matches " + matches.size()
                            + " arrows; use the numeric id from 'arrow list'");
        }
        throw new IllegalArgumentException("No arrow with id or name '" + selector + "'");
    }

    // -------------------------------------------------------------- sides

    /**
     * Maps an IDEF0 side word to the MovingPanel constant.
     * Inputs enter on the left, controls on top, mechanisms from the bottom,
     * outputs leave on the right.
     */
    static int side(String value, String argName) {
        if (value == null || value.trim().length() == 0) {
            throw new IllegalArgumentException("Missing required argument: " + argName);
        }
        String v = value.trim().toLowerCase();
        if ("left".equals(v) || "input".equals(v) || "in".equals(v)) {
            return MovingPanel.LEFT;
        }
        if ("right".equals(v) || "output".equals(v) || "out".equals(v)) {
            return MovingPanel.RIGHT;
        }
        if ("top".equals(v) || "control".equals(v)) {
            return MovingPanel.TOP;
        }
        if ("bottom".equals(v) || "mechanism".equals(v)) {
            return MovingPanel.BOTTOM;
        }
        throw new IllegalArgumentException(
                "Unknown side '" + value + "' for " + argName
                        + ". Use one of: input/left, control/top, mechanism/bottom, output/right");
    }

    static String sideName(int side) {
        switch (side) {
            case MovingPanel.LEFT:
                return "input";
            case MovingPanel.RIGHT:
                return "output";
            case MovingPanel.TOP:
                return "control";
            case MovingPanel.BOTTOM:
                return "mechanism";
            default:
                return "side" + side;
        }
    }

    // --------------------------------------------------------- classifiers

    /**
     * User-visible classifiers: every qualifier that is not an IDEF0 function
     * qualifier and not one of the engine's own system qualifiers.
     */
    static List<Qualifier> classifiers(Engine engine) {
        List<Qualifier> system = engine.getSystemQualifiers();
        List<Qualifier> result = new ArrayList<Qualifier>();
        for (Object o : engine.getQualifiers()) {
            Qualifier q = (Qualifier) o;
            if (IDEF0Plugin.isFunction(q)) {
                continue;
            }
            boolean isSystem = false;
            for (Qualifier sq : system) {
                if (sq.getId() == q.getId()) {
                    isSystem = true;
                    break;
                }
            }
            if (!isSystem) {
                result.add(q);
            }
        }
        return result;
    }

    static Qualifier classifier(Engine engine, String selector) {
        if (selector == null || selector.trim().length() == 0) {
            throw new IllegalArgumentException("Missing required argument: classifier");
        }
        selector = selector.trim();
        List<Qualifier> all = classifiers(engine);
        for (Qualifier q : all) {
            if (selector.equals(Long.toString(q.getId()))) {
                return q;
            }
        }
        for (Qualifier q : all) {
            if (selector.equals(q.getName())) {
                return q;
            }
        }
        for (Qualifier q : all) {
            if (selector.equalsIgnoreCase(q.getName())) {
                return q;
            }
        }
        throw new IllegalArgumentException("No classifier named or numbered '" + selector + "'");
    }
}
