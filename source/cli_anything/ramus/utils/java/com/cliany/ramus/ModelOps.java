package com.cliany.ramus;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.dsoft.pb.idef.elements.ProjectOptions;
import com.ramussoft.common.Attribute;
import com.ramussoft.common.Qualifier;
import com.ramussoft.idef0.IDEF0Plugin;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;

/** IDEF0 / DFD / DFDS models — one model is one Ramus function qualifier. */
final class ModelOps {

    private ModelOps() {
    }

    static Object dispatch(RamusBridge.Ops ops, String op, Map<String, Object> args) throws Exception {
        if ("model.list".equals(op)) {
            return list(ops);
        }
        if ("model.create".equals(op)) {
            return create(ops, args);
        }
        if ("model.info".equals(op)) {
            return info(ops, args);
        }
        if ("model.rename".equals(op)) {
            return rename(ops, args);
        }
        if ("model.delete".equals(op)) {
            return delete(ops, args);
        }
        if ("model.tree".equals(op)) {
            return tree(ops, args);
        }
        if ("model.set-options".equals(op)) {
            return setOptions(ops, args);
        }
        throw new IllegalArgumentException("Unknown operation: " + op);
    }

    static Map<String, Object> list(RamusBridge.Ops ops) {
        ops.requireOpen();
        List<Object> models = new ArrayList<Object>();
        for (Qualifier q : Resolve.models(ops.engine)) {
            models.add(describe(ops, q, false));
        }
        Map<String, Object> m = Json.obj();
        m.put("models", models);
        m.put("count", Integer.valueOf(models.size()));
        return m;
    }

    static Map<String, Object> describe(RamusBridge.Ops ops, Qualifier q, boolean deep) {
        DataPlugin dp = Resolve.plugin(ops, q);
        Function base = dp.getBaseFunction();
        Map<String, Object> m = Json.obj();
        m.put("id", Long.valueOf(q.getId()));
        m.put("name", q.getName());
        m.put("diagram_type", ProjectOps.diagramTypeName(base.getDecompositionType()));
        List<Function> functions = Resolve.allFunctions(dp);
        m.put("function_count", Integer.valueOf(functions.size()));
        m.put("arrow_count", Integer.valueOf(dp.getAllSectors().size()));
        m.put("decomposed_diagrams", Integer.valueOf(diagramCount(dp)));
        if (deep) {
            ProjectOptions po = base.getProjectOptions();
            Map<String, Object> options = Json.obj();
            options.put("author", po == null ? "" : nullToEmpty(po.getProjectAutor()));
            options.put("project", po == null ? "" : nullToEmpty(po.getProjectName()));
            options.put("definition", po == null ? "" : nullToEmpty(po.getDefinition()));
            options.put("used_at", po == null ? "" : nullToEmpty(po.getUsedAt()));
            m.put("options", options);
            m.put("page_size", base.getPageSize() == null ? "A4" : base.getPageSize());
        }
        return m;
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    /** Diagrams that actually exist: every function that has been decomposed. */
    static int diagramCount(DataPlugin dp) {
        int count = 0;
        for (Function f : Resolve.allFunctions(dp)) {
            if (f.isHaveRealChilds()) {
                count++;
            }
        }
        return count;
    }

    static Map<String, Object> create(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final String name = Json.reqStr(args, "name");
        for (Qualifier q : Resolve.models(ops.engine)) {
            if (name.equals(q.getName())) {
                throw new IllegalStateException("A model named '" + name + "' already exists (id " + q.getId() + ")");
            }
        }
        final int type = ProjectOps.diagramType(Json.str(args, "diagram_type", "idef0"));
        Qualifier model = ops.inTransaction(new RamusBridge.Task<Qualifier>() {
            public Qualifier run() {
                return createModel(ops, name, type);
            }
        });
        return describe(ops, model, true);
    }

    /**
     * Creates the qualifier that backs a model and wires up everything Ramus
     * expects: the shared Name attribute, the IDEF0 visual attributes, the
     * diagram type, and the model-tree entry.
     * Must be called inside a user transaction.
     */
    static Qualifier createModel(RamusBridge.Ops ops, String name, int diagramType) {
        Attribute nameAttribute = ops.nameAttribute();
        Qualifier model = ops.engine.createQualifier();
        model.setName(name);
        model.getAttributes().add(nameAttribute);
        model.setAttributeForName(nameAttribute.getId());
        IDEF0Plugin.installFunctionAttributes(model, ops.engine);
        ops.engine.updateQualifier(model);

        DataPlugin dp = Resolve.plugin(ops, model);
        if (diagramType != ProjectOps.DIAGRAM_IDEF0) {
            dp.getBaseFunction().setDecompositionType(diagramType);
        }
        ProjectOps.registerInModelTree(ops.engine, model);
        return model;
    }

    static Map<String, Object> info(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        return describe(ops, q, true);
    }

    static Map<String, Object> rename(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        final Qualifier q = Resolve.model(ops, args);
        final String name = Json.reqStr(args, "name");
        final String old = q.getName();
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                q.setName(name);
                ops.engine.updateQualifier(q);
                return null;
            }
        });
        Map<String, Object> m = describe(ops, ops.engine.getQualifier(q.getId()), false);
        m.put("previous_name", old);
        return m;
    }

    static Map<String, Object> delete(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        final Qualifier q = Resolve.model(ops, args);
        final long id = q.getId();
        final String name = q.getName();
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                ops.engine.deleteQualifier(id);
                return null;
            }
        });
        Map<String, Object> m = Json.obj();
        m.put("deleted", Boolean.TRUE);
        m.put("id", Long.valueOf(id));
        m.put("name", name);
        return m;
    }

    static Map<String, Object> tree(RamusBridge.Ops ops, Map<String, Object> args) {
        Qualifier q = Resolve.model(ops, args);
        DataPlugin dp = Resolve.plugin(ops, q);
        Function base = dp.getBaseFunction();
        Map<String, Object> m = Json.obj();
        m.put("model", q.getName());
        m.put("model_id", Long.valueOf(q.getId()));
        m.put("root", node(dp, base));
        return m;
    }

    private static Map<String, Object> node(DataPlugin dp, Function f) {
        Map<String, Object> m = Json.obj();
        m.put("id", Long.valueOf(Resolve.elementId(f)));
        m.put("node", Resolve.node(dp, f));
        m.put("name", f.getName());
        List<Object> children = new ArrayList<Object>();
        for (Function child : Resolve.children(dp, f)) {
            children.add(node(dp, child));
        }
        m.put("children", children);
        m.put("child_count", Integer.valueOf(children.size()));
        return m;
    }

    static Map<String, Object> setOptions(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        final Qualifier q = Resolve.model(ops, args);
        final DataPlugin dp = Resolve.plugin(ops, q);
        final Function base = dp.getBaseFunction();
        final Map<String, Object> a = args;
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                ProjectOptions po = base.getProjectOptions();
                if (po == null) {
                    po = new ProjectOptions();
                }
                if (a.containsKey("author")) {
                    po.setProjectAutor(Json.str(a, "author", ""));
                }
                if (a.containsKey("project")) {
                    po.setProjectName(Json.str(a, "project", ""));
                }
                if (a.containsKey("definition")) {
                    po.setDefinition(Json.str(a, "definition", ""));
                }
                if (a.containsKey("used_at")) {
                    po.setUsedAt(Json.str(a, "used_at", ""));
                }
                base.setProjectOptions(po);
                if (a.containsKey("page_size")) {
                    base.setPageSize(Json.str(a, "page_size", "A4"));
                }
                return null;
            }
        });
        return describe(ops, q, true);
    }
}
