package com.cliany.ramus;

import java.io.File;
import java.io.ObjectOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Properties;

import com.dsoft.pb.idef.elements.ProjectOptions;
import com.ramussoft.common.Attribute;
import com.ramussoft.common.Element;
import com.ramussoft.common.Engine;
import com.ramussoft.common.Qualifier;
import com.ramussoft.core.attribute.simple.HierarchicalPersistent;
import com.ramussoft.core.attribute.standard.AutochangePlugin;
import com.ramussoft.core.attribute.standard.StandardAttributesPlugin;
import com.ramussoft.idef0.IDEF0Plugin;
import com.ramussoft.idef0.IDEF0ViewPlugin;
import com.ramussoft.idef0.OpenDiagram;
import com.ramussoft.gui.common.event.ActionEvent;
import com.ramussoft.pb.DataPlugin;
import com.ramussoft.pb.Function;
import com.ramussoft.pb.Row;
import com.ramussoft.pb.idef.visual.MovingArea;

/** Project lifecycle: create, open, save, describe. */
final class ProjectOps {

    private ProjectOps() {
    }

    static final int DIAGRAM_IDEF0 = 0;
    static final int DIAGRAM_DFD = MovingArea.DIAGRAM_TYPE_DFD;
    static final int DIAGRAM_DFDS = MovingArea.DIAGRAM_TYPE_DFDS;

    static int diagramType(String value) {
        if (value == null || value.trim().length() == 0) {
            return DIAGRAM_IDEF0;
        }
        String v = value.trim().toLowerCase();
        if ("idef0".equals(v)) {
            return DIAGRAM_IDEF0;
        }
        if ("dfd".equals(v)) {
            return DIAGRAM_DFD;
        }
        if ("dfds".equals(v)) {
            return DIAGRAM_DFDS;
        }
        throw new IllegalArgumentException(
                "Unknown diagram type '" + value + "'. Use one of: idef0, dfd, dfds");
    }

    static String diagramTypeName(int type) {
        if (type == DIAGRAM_DFD) {
            return "dfd";
        }
        if (type == DIAGRAM_DFDS) {
            return "dfds";
        }
        return "idef0";
    }

    /**
     * Builds a new .rsf the same way the Ramus new-project wizard does: a
     * function qualifier carrying the IDEF0 attributes, a shared Name
     * attribute registered for auto-add, an entry in the model tree so the
     * GUI lists the model, project options, and any starting classifiers.
     */
    static Map<String, Object> newProject(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        File target = RamusBridge.resolve(Json.reqStr(args, "path"));
        boolean overwrite = Json.bool(args, "overwrite", false);
        if (target.exists() && !overwrite) {
            throw new IllegalStateException(
                    "File already exists: " + target.getAbsolutePath() + " (pass --overwrite to replace it)");
        }
        String modelName = Json.str(args, "model_name", "A0");
        int type = diagramType(Json.str(args, "diagram_type", "idef0"));

        ops.createEmpty();
        final Engine engine = ops.engine;

        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                Attribute name = ops.nameAttribute();

                Properties ps = engine.getProperties(AutochangePlugin.AUTO_ADD_ATTRIBUTES);
                ps.setProperty(AutochangePlugin.AUTO_ADD_ATTRIBUTE_IDS, Long.toString(name.getId()));
                ps.setProperty(AutochangePlugin.ATTRIBUTE_FOR_NAME, Long.toString(name.getId()));
                engine.setProperties(AutochangePlugin.AUTO_ADD_ATTRIBUTES, ps);
                return null;
            }
        });

        final String finalModelName = modelName;
        final int finalType = type;
        Qualifier model = ops.inTransaction(new RamusBridge.Task<Qualifier>() {
            public Qualifier run() {
                return ModelOps.createModel(ops, finalModelName, finalType);
            }
        });

        final ProjectOptions options = new ProjectOptions();
        options.setProjectAutor(Json.str(args, "author", ""));
        options.setProjectName(Json.str(args, "project", ""));
        options.setDefinition(Json.str(args, "definition", ""));
        options.setUsedAt(Json.str(args, "used_at", ""));

        final Qualifier finalModel = model;
        final List<Object> classifierNames = Json.list(args, "classifiers");
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                DataPlugin dp = Resolve.plugin(ops, finalModel);
                dp.getBaseFunction().setProjectOptions(options);
                StringBuilder ownerIds = new StringBuilder();
                for (Object o : classifierNames) {
                    String cname = o.toString().trim();
                    if (cname.length() == 0) {
                        continue;
                    }
                    Row row = dp.createRow(null, false);
                    Qualifier q = engine.getQualifier(
                            StandardAttributesPlugin.getQualifierId(engine, row.getElement().getId()));
                    q.setName(cname);
                    engine.updateQualifier(q);
                    ownerIds.append(q.getId()).append(' ');
                }
                if (ownerIds.length() > 0) {
                    dp.setProperty(DataPlugin.PROPERTY_OUNERS, ownerIds.toString());
                }
                return null;
            }
        });

        // Runner restores diagram tabs from this stream; without it a new
        // CLI project opens as a blank workspace in the desktop application.
        List<ActionEvent> tabs = new ArrayList<ActionEvent>();
        tabs.add(new ActionEvent(IDEF0ViewPlugin.OPEN_DIAGRAM, new OpenDiagram(model, -1L)));
        try (ObjectOutputStream out = new ObjectOutputStream(
                engine.getOutputStream("/user/gui/session.binary"))) {
            out.writeObject(tabs);
        }
        ops.saveTo(target);
        Map<String, Object> result = info(ops);
        result.put("created", Boolean.TRUE);
        return result;
    }

    static Map<String, Object> open(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        File file = RamusBridge.resolve(Json.reqStr(args, "path"));
        if (!file.isFile()) {
            throw new java.io.FileNotFoundException("Project file not found: " + file.getAbsolutePath());
        }
        ops.openFile(file);
        return info(ops);
    }

    static Map<String, Object> save(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        String path = Json.str(args, "path", null);
        File target = path == null ? ops.path : RamusBridge.resolve(path);
        if (target == null) {
            throw new IllegalStateException("This project has no file yet; pass a path to save-as");
        }
        boolean overwrite = Json.bool(args, "overwrite", true);
        if (path != null && target.exists() && !overwrite) {
            throw new IllegalStateException(
                    "File already exists: " + target.getAbsolutePath() + " (pass --overwrite to replace it)");
        }
        String saved = ops.saveTo(target);
        Map<String, Object> m = Json.obj();
        m.put("path", saved);
        m.put("file_size", Long.valueOf(new File(saved).length()));
        m.put("saved", Boolean.TRUE);
        return m;
    }

    /**
     * Writes a copy of the open project without adopting the new path.
     *
     * Undo snapshots need a byte-exact copy of the current state, but they must
     * not make the snapshot file the project the session is editing.
     */
    static Map<String, Object> saveCopy(RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        File target = RamusBridge.resolve(Json.reqStr(args, "path"));
        File originalPath = ops.path;
        boolean originalModified = ops.modified;
        ops.saveTo(target);
        ops.path = originalPath;
        ops.modified = originalModified;
        Map<String, Object> m = Json.obj();
        m.put("path", target.getAbsolutePath());
        m.put("file_size", Long.valueOf(target.length()));
        m.put("project_path", originalPath == null ? null : originalPath.getAbsolutePath());
        return m;
    }

    static Map<String, Object> close(RamusBridge.Ops ops) {
        boolean wasOpen = ops.engine != null;
        boolean wasModified = ops.modified;
        ops.closeQuietly();
        Map<String, Object> m = Json.obj();
        m.put("closed", Boolean.valueOf(wasOpen));
        m.put("discarded_changes", Boolean.valueOf(wasModified));
        return m;
    }

    static Map<String, Object> info(RamusBridge.Ops ops) {
        ops.requireOpen();
        Map<String, Object> m = Json.obj();
        m.put("path", ops.path == null ? null : ops.path.getAbsolutePath());
        m.put("file_size", ops.path == null || !ops.path.isFile()
                ? Long.valueOf(0) : Long.valueOf(ops.path.length()));
        m.put("modified", Boolean.valueOf(ops.modified));

        List<Object> models = new ArrayList<Object>();
        int functionTotal = 0;
        int arrowTotal = 0;
        for (Qualifier q : Resolve.models(ops.engine)) {
            DataPlugin dp = Resolve.plugin(ops, q);
            List<Function> functions = Resolve.allFunctions(dp);
            int arrows = dp.getAllSectors().size();
            functionTotal += functions.size();
            arrowTotal += arrows;
            Map<String, Object> mm = Json.obj();
            mm.put("id", Long.valueOf(q.getId()));
            mm.put("name", q.getName());
            mm.put("diagram_type", diagramTypeName(dp.getBaseFunction().getDecompositionType()));
            mm.put("function_count", Integer.valueOf(functions.size()));
            mm.put("arrow_count", Integer.valueOf(arrows));
            models.add(mm);
        }
        m.put("models", models);
        m.put("model_count", Integer.valueOf(models.size()));
        m.put("function_count", Integer.valueOf(functionTotal));
        m.put("arrow_count", Integer.valueOf(arrowTotal));

        List<Object> classifiers = new ArrayList<Object>();
        for (Qualifier q : Resolve.classifiers(ops.engine)) {
            Map<String, Object> cm = Json.obj();
            cm.put("id", Long.valueOf(q.getId()));
            cm.put("name", q.getName());
            cm.put("element_count", Long.valueOf(ops.engine.getElementCountForQualifier(q.getId())));
            classifiers.add(cm);
        }
        m.put("classifiers", classifiers);
        m.put("classifier_count", Integer.valueOf(classifiers.size()));
        return m;
    }

    /**
     * Registers a model qualifier in the IDEF0 model tree so that the Ramus
     * GUI shows it in the model navigator.
     */
    static void registerInModelTree(Engine engine, Qualifier model) {
        Qualifier tree = IDEF0Plugin.getModelTree(engine);
        if (tree == null) {
            return;
        }
        Element element = engine.createElement(tree.getId());
        engine.setAttribute(element, StandardAttributesPlugin.getAttributeQualifierId(engine),
                Long.valueOf(model.getId()));
        engine.setAttribute(element, StandardAttributesPlugin.getAttributeNameAttribute(engine),
                model.getName());
        HierarchicalPersistent hp = new HierarchicalPersistent();
        hp.setParentElementId(-1L);
        hp.setPreviousElementId(-1L);
        engine.setAttribute(element, StandardAttributesPlugin.getHierarchicalAttribute(engine), hp);
    }
}
