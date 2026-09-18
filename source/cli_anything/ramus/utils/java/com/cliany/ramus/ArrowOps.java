package com.cliany.ramus;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.dsoft.pb.types.FRectangle;
import com.ramussoft.common.Qualifier;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;
import com.ramussoft.pb.Sector;
import com.ramussoft.pb.Stream;
import com.ramussoft.pb.data.negine.NSectorBorder;
import com.ramussoft.pb.idef.elements.Ordinate;
import com.ramussoft.pb.idef.elements.PaintSector;
import com.ramussoft.pb.idef.elements.Point;
import com.ramussoft.pb.idef.elements.ReplaceStreamType;
import com.ramussoft.pb.idef.elements.SectorRefactor;
import com.ramussoft.pb.idef.visual.MovingArea;
import com.ramussoft.pb.idef.visual.MovingPanel;

/**
 * Arrows ("sectors" in Ramus terms).
 *
 * <p>An arrow lives on the diagram that decomposes one function, and connects a
 * side of a child box (or the diagram border) to a side of another. The label
 * text is carried by a "stream" row in the model's arrow dictionary, which is
 * exactly how the Ramus GUI stores it.
 */
final class ArrowOps {

    private ArrowOps() {
    }

    /** Distance kept between the diagram border and a border arrow endpoint. */
    private static final double BORDER_MARGIN = 7.0;

    static Object dispatch(RamusBridge.Ops ops, String op, Map<String, Object> args) throws Exception {
        if ("arrow.list".equals(op)) {
            return list(ops, args);
        }
        if ("arrow.add".equals(op)) {
            return add(ops, args);
        }
        if ("arrow.rename".equals(op)) {
            return rename(ops, args);
        }
        if ("arrow.delete".equals(op)) {
            return delete(ops, args);
        }
        if ("arrow.streams".equals(op)) {
            return streams(ops, args);
        }
        throw new IllegalArgumentException("Unknown operation: " + op);
    }

    // ------------------------------------------------------------ describe

    static Map<String, Object> describe(DataPlugin dp, Sector s) {
        Map<String, Object> m = Json.obj();
        m.put("id", Long.valueOf(Resolve.sectorId(s)));
        String name = s.getName();
        m.put("name", name == null ? "" : name);
        m.put("from", endpoint(dp, s.getStart()));
        m.put("to", endpoint(dp, s.getEnd()));
        Function diagram = s.getFunction();
        m.put("diagram_id", diagram == null ? null : Long.valueOf(Resolve.elementId(diagram)));
        m.put("diagram", diagram == null ? null : diagram.getName());
        m.put("diagram_node", diagram == null ? null : Resolve.node(dp, diagram));
        return m;
    }

    private static Map<String, Object> endpoint(DataPlugin dp, NSectorBorder border) {
        Map<String, Object> m = Json.obj();
        if (border == null) {
            m.put("kind", "unset");
            return m;
        }
        Function f = border.getFunction();
        if (f != null) {
            m.put("kind", "function");
            m.put("function_id", Long.valueOf(Resolve.elementId(f)));
            m.put("function", f.getName());
            m.put("node", Resolve.node(dp, f));
            m.put("side", Resolve.sideName(border.getFunctionType()));
        } else {
            m.put("kind", "border");
            m.put("side", Resolve.sideName(border.getBorderType()));
        }
        return m;
    }

    // ---------------------------------------------------------------- list

    static Map<String, Object> list(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        String diagramSelector = Json.str(args, "diagram", null);

        List<Sector> sectors;
        Function diagram = null;
        if (diagramSelector == null) {
            sectors = new ArrayList<Sector>();
            for (Object o : dp.getAllSectors()) {
                sectors.add((Sector) o);
            }
        } else {
            diagram = Resolve.function(dp, diagramSelector, "diagram");
            sectors = Resolve.sectorsOf(dp, diagram);
        }

        List<Object> out = new ArrayList<Object>();
        for (Sector s : sectors) {
            out.add(describe(dp, s));
        }
        Map<String, Object> m = Json.obj();
        m.put("model", q.getName());
        m.put("model_id", Long.valueOf(q.getId()));
        m.put("diagram", diagram == null ? null : diagram.getName());
        m.put("arrows", out);
        m.put("count", Integer.valueOf(out.size()));
        return m;
    }

    /** The model's arrow dictionary — every distinct label defined so far. */
    static Map<String, Object> streams(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        List<Object> out = new ArrayList<Object>();
        for (Object o : dp.getChilds(dp.getBaseStream(), true)) {
            com.ramussoft.pb.Row row = (com.ramussoft.pb.Row) o;
            Map<String, Object> m = Json.obj();
            m.put("id", Long.valueOf(Resolve.elementId(row)));
            m.put("name", row.getName());
            out.add(m);
        }
        Map<String, Object> m = Json.obj();
        m.put("model", q.getName());
        m.put("streams", out);
        m.put("count", Integer.valueOf(out.size()));
        return m;
    }

    // ----------------------------------------------------------------- add

    static Map<String, Object> add(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        final Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);

        String diagramSelector = Json.str(args, "diagram", null);
        final Function diagram = diagramSelector == null
                ? dp.getBaseFunction()
                : Resolve.function(dp, diagramSelector, "diagram");

        final String fromSelector = Json.reqStr(args, "from");
        final String toSelector = Json.reqStr(args, "to");
        final boolean fromBorder = isBorder(fromSelector);
        final boolean toBorder = isBorder(toSelector);
        if (fromBorder && toBorder) {
            throw new IllegalArgumentException(
                    "At least one arrow endpoint must be a function; border-to-border arrows are not meaningful");
        }

        final Function fromFunction = fromBorder ? null : Resolve.function(dp, fromSelector, "from");
        final Function toFunction = toBorder ? null : Resolve.function(dp, toSelector, "to");
        // An arrow leaves a box on its output side and arrives on an input side
        // unless the caller says otherwise.
        final int fromSide = Resolve.side(Json.str(args, "from_side", "output"), "from_side");
        final int toSide = Resolve.side(Json.str(args, "to_side", "input"), "to_side");
        final String label = Json.str(args, "name", null);

        for (Function f : new Function[]{fromFunction, toFunction}) {
            if (f != null && !isOnDiagram(dp, diagram, f)) {
                throw new IllegalArgumentException("Function '" + f.getName()
                        + "' is not a child of diagram '" + diagram.getName()
                        + "'; arrows connect boxes drawn on the same diagram");
            }
        }

        Sector created = ops.inTransaction(new RamusBridge.Task<Sector>() {
            public Sector run() {
                MovingArea area = new MovingArea(dp, diagram);
                area.setActiveFunction(diagram);
                SectorRefactor refactor = area.getRefactor();

                Sector s = dp.createSector();
                s.setFunction(diagram);

                NSectorBorder start = s.getStart();
                if (fromBorder) {
                    start.setBorderTypeA(fromSide);
                } else {
                    start.setFunctionA(fromFunction);
                    start.setFunctionTypeA(fromSide);
                }
                start.commit();

                NSectorBorder end = s.getEnd();
                if (toBorder) {
                    end.setBorderTypeA(toSide);
                } else {
                    end.setFunctionA(toFunction);
                    end.setFunctionTypeA(toSide);
                }
                end.commit();

                if (label != null && label.length() > 0) {
                    Stream stream = (Stream) dp.createRow(dp.getBaseStream(), true);
                    stream.setName(label);
                    s.setStream(stream, ReplaceStreamType.CHILDREN);
                }

                double[] a = anchor(area, fromFunction, fromSide, fromBorder);
                double[] b = anchor(area, toFunction, toSide, toBorder);
                // A border endpoint lines up with the box it feeds, so the
                // arrow enters the diagram on a straight run.
                if (fromBorder && toFunction != null) {
                    if (fromSide == MovingPanel.LEFT || fromSide == MovingPanel.RIGHT) {
                        a[1] = b[1];
                    } else {
                        a[0] = b[0];
                    }
                }
                if (toBorder && fromFunction != null) {
                    if (toSide == MovingPanel.LEFT || toSide == MovingPanel.RIGHT) {
                        b[1] = a[1];
                    } else {
                        b[0] = a[0];
                    }
                }

                PaintSector ps = new PaintSector(s, point(a, fromBorder, fromSide),
                        point(b, toBorder, toSide), area);
                refactor.addSector(ps);
                ps.savePointOrdinates();
                refactor.lightSaveToFunction();
                return s;
            }
        });

        Map<String, Object> m = describe(dp, created);
        m.put("model", q.getName());
        m.put("created", Boolean.TRUE);
        return m;
    }

    static boolean isBorder(String selector) {
        return selector != null && "border".equalsIgnoreCase(selector.trim());
    }

    private static boolean isOnDiagram(DataPlugin dp, Function diagram, Function f) {
        for (Function child : Resolve.children(dp, diagram)) {
            if (Resolve.sameRow(child, f)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Builds a routing point.
     *
     * <p>For a border endpoint the point type is set explicitly. Ramus derives
     * it lazily from the sector's border, but that lookup goes through a
     * back-reference the PaintSector only installs after construction, so
     * leaving it unset makes {@code PointBuilder} dereference null while it is
     * still laying out the very sector that would supply it. The value written
     * here is the one Ramus itself would derive: a line leaving a left or right
     * border runs horizontally, one leaving top or bottom runs vertically.
     */
    private static Point point(double[] xy, boolean border, int side) {
        Ordinate x = new Ordinate(Ordinate.TYPE_X);
        x.setPosition(xy[0]);
        Ordinate y = new Ordinate(Ordinate.TYPE_Y);
        y.setPosition(xy[1]);
        Point p = new Point(x, y);
        if (border) {
            p.setType(side == MovingPanel.LEFT || side == MovingPanel.RIGHT
                    ? Ordinate.TYPE_X : Ordinate.TYPE_Y);
        }
        return p;
    }

    /** Where the arrow touches a box side, or the diagram border. */
    private static double[] anchor(MovingArea area, Function f, int side, boolean border) {
        if (border) {
            double width = area.getDoubleWidth();
            double height = area.CLIENT_HEIGHT;
            switch (side) {
                case MovingPanel.LEFT:
                    return new double[]{BORDER_MARGIN, height / 2.0};
                case MovingPanel.RIGHT:
                    return new double[]{width - BORDER_MARGIN, height / 2.0};
                case MovingPanel.TOP:
                    return new double[]{width / 2.0, BORDER_MARGIN};
                default:
                    return new double[]{width / 2.0, height - BORDER_MARGIN};
            }
        }
        FRectangle b = f.getBounds();
        switch (side) {
            case MovingPanel.LEFT:
                return new double[]{b.getX(), b.getY() + b.getHeight() / 2.0};
            case MovingPanel.RIGHT:
                return new double[]{b.getX() + b.getWidth(), b.getY() + b.getHeight() / 2.0};
            case MovingPanel.TOP:
                return new double[]{b.getX() + b.getWidth() / 2.0, b.getY()};
            default:
                return new double[]{b.getX() + b.getWidth() / 2.0, b.getY() + b.getHeight()};
        }
    }

    // -------------------------------------------------------------- mutate

    static Map<String, Object> rename(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Sector s = Resolve.sector(dp, Json.reqStr(args, "id"));
        final String name = Json.reqStr(args, "name");
        final String old = s.getName();
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                Stream stream = s.getStream();
                if (stream == null) {
                    stream = (Stream) dp.createRow(dp.getBaseStream(), true);
                    stream.setName(name);
                    s.setStream(stream, ReplaceStreamType.CHILDREN);
                } else {
                    stream.setName(name);
                }
                return null;
            }
        });
        Map<String, Object> m = describe(dp, s);
        m.put("previous_name", old == null ? "" : old);
        return m;
    }

    static Map<String, Object> delete(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Sector s = Resolve.sector(dp, Json.reqStr(args, "id"));
        final long id = Resolve.sectorId(s);
        final String name = s.getName();
        final Function diagram = s.getFunction();

        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                s.remove();
                if (diagram != null) {
                    // Rewrite the diagram's stored geometry without this arrow.
                    MovingArea area = new MovingArea(dp, diagram);
                    area.setActiveFunction(diagram);
                    area.getRefactor().saveToFunction();
                }
                return null;
            }
        });

        Map<String, Object> m = Json.obj();
        m.put("deleted", Boolean.TRUE);
        m.put("id", Long.valueOf(id));
        m.put("name", name == null ? "" : name);
        return m;
    }
}
