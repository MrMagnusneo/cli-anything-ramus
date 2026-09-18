package com.cliany.ramus;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.ramussoft.common.Attribute;
import com.ramussoft.common.Qualifier;
import com.ramussoft.database.common.Row;
import com.ramussoft.database.common.RowSet;

/**
 * Ramus's generic data layer: classifiers (qualifiers) and their elements.
 *
 * <p>Classifiers hold the reference data an IDEF0 model points at — roles,
 * documents, resources — and appear in the Ramus GUI's classifier tree.
 */
final class DataOps {

    private DataOps() {
    }

    static Object dispatch(RamusBridge.Ops ops, String op, Map<String, Object> args) throws Exception {
        if ("classifier.list".equals(op)) {
            return listClassifiers(ops);
        }
        if ("classifier.create".equals(op)) {
            return createClassifier(ops, args);
        }
        if ("classifier.rename".equals(op)) {
            return renameClassifier(ops, args);
        }
        if ("classifier.delete".equals(op)) {
            return deleteClassifier(ops, args);
        }
        if ("classifier.show".equals(op)) {
            return showClassifier(ops, args);
        }
        if ("element.list".equals(op)) {
            return listElements(ops, args);
        }
        if ("element.add".equals(op)) {
            return addElement(ops, args);
        }
        if ("element.rename".equals(op)) {
            return renameElement(ops, args);
        }
        if ("element.delete".equals(op)) {
            return deleteElement(ops, args);
        }
        throw new IllegalArgumentException("Unknown operation: " + op);
    }

    // --------------------------------------------------------- classifiers

    static Map<String, Object> describe(RamusBridge.Ops ops, Qualifier q) {
        Map<String, Object> m = Json.obj();
        m.put("id", Long.valueOf(q.getId()));
        m.put("name", q.getName());
        m.put("element_count", Long.valueOf(ops.engine.getElementCountForQualifier(q.getId())));
        List<Object> attributes = new ArrayList<Object>();
        for (Object o : q.getAttributes()) {
            Attribute a = (Attribute) o;
            Map<String, Object> am = Json.obj();
            am.put("id", Long.valueOf(a.getId()));
            am.put("name", a.getName());
            am.put("type", a.getAttributeType().toString());
            attributes.add(am);
        }
        m.put("attributes", attributes);
        return m;
    }

    static Map<String, Object> listClassifiers(RamusBridge.Ops ops) {
        ops.requireOpen();
        List<Object> out = new ArrayList<Object>();
        for (Qualifier q : Resolve.classifiers(ops.engine)) {
            out.add(describe(ops, q));
        }
        Map<String, Object> m = Json.obj();
        m.put("classifiers", out);
        m.put("count", Integer.valueOf(out.size()));
        return m;
    }

    static Map<String, Object> createClassifier(final RamusBridge.Ops ops,
                                                Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final String name = Json.reqStr(args, "name");
        for (Qualifier q : Resolve.classifiers(ops.engine)) {
            if (name.equals(q.getName())) {
                throw new IllegalStateException(
                        "A classifier named '" + name + "' already exists (id " + q.getId() + ")");
            }
        }
        Qualifier created = ops.inTransaction(new RamusBridge.Task<Qualifier>() {
            public Qualifier run() {
                Attribute nameAttribute = ops.nameAttribute();
                Qualifier q = ops.engine.createQualifier();
                q.setName(name);
                if (!q.getAttributes().contains(nameAttribute)) {
                    q.getAttributes().add(nameAttribute);
                }
                q.setAttributeForName(nameAttribute.getId());
                ops.engine.updateQualifier(q);
                return q;
            }
        });
        Map<String, Object> m = describe(ops, ops.engine.getQualifier(created.getId()));
        m.put("created", Boolean.TRUE);
        return m;
    }

    static Map<String, Object> renameClassifier(final RamusBridge.Ops ops,
                                                Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        final String name = Json.reqStr(args, "name");
        final String old = q.getName();
        ops.inTransaction(new RamusBridge.Task<Object>() {
            public Object run() {
                q.setName(name);
                ops.engine.updateQualifier(q);
                return null;
            }
        });
        Map<String, Object> m = describe(ops, ops.engine.getQualifier(q.getId()));
        m.put("previous_name", old);
        return m;
    }

    static Map<String, Object> deleteClassifier(final RamusBridge.Ops ops,
                                                Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
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

    static Map<String, Object> showClassifier(RamusBridge.Ops ops, Map<String, Object> args) {
        ops.requireOpen();
        Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        Map<String, Object> m = describe(ops, q);
        RowSet rowSet = new RowSet(ops.engine, q, new Attribute[]{});
        try {
            m.put("elements", elementTree(rowSet.getRoot()));
        } finally {
            rowSet.close();
        }
        return m;
    }

    private static List<Object> elementTree(Row parent) {
        List<Object> out = new ArrayList<Object>();
        for (Row child : parent.getChildren()) {
            Map<String, Object> m = Json.obj();
            m.put("id", Long.valueOf(child.getElementId()));
            m.put("name", child.getName());
            m.put("children", elementTree(child));
            out.add(m);
        }
        return out;
    }

    // ------------------------------------------------------------ elements

    static Map<String, Object> listElements(RamusBridge.Ops ops, Map<String, Object> args) {
        ops.requireOpen();
        Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        RowSet rowSet = new RowSet(ops.engine, q, new Attribute[]{});
        try {
            List<Object> out = new ArrayList<Object>();
            for (Row row : rowSet.getAllRows()) {
                Map<String, Object> m = Json.obj();
                m.put("id", Long.valueOf(row.getElementId()));
                m.put("name", row.getName());
                Row parent = row.getParent();
                boolean topLevel = parent == null || parent.getElementId() < 0;
                m.put("parent_id", topLevel ? null : Long.valueOf(parent.getElementId()));
                out.add(m);
            }
            Map<String, Object> m = Json.obj();
            m.put("classifier", q.getName());
            m.put("classifier_id", Long.valueOf(q.getId()));
            m.put("elements", out);
            m.put("count", Integer.valueOf(out.size()));
            return m;
        } finally {
            rowSet.close();
        }
    }

    static Map<String, Object> addElement(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        final Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        final String name = Json.reqStr(args, "name");
        final String parentSelector = Json.str(args, "parent", null);

        final RowSet rowSet = new RowSet(ops.engine, q, new Attribute[]{});
        try {
            final Row parent = parentSelector == null
                    ? rowSet.getRoot()
                    : findRow(rowSet, parentSelector, "parent");
            Row created = ops.inTransaction(new RamusBridge.Task<Row>() {
                public Row run() {
                    Row row = rowSet.createRow(parent);
                    row.setName(name);
                    return row;
                }
            });
            Map<String, Object> m = Json.obj();
            m.put("created", Boolean.TRUE);
            m.put("id", Long.valueOf(created.getElementId()));
            m.put("name", created.getName());
            m.put("classifier", q.getName());
            m.put("classifier_id", Long.valueOf(q.getId()));
            return m;
        } finally {
            rowSet.close();
        }
    }

    static Map<String, Object> renameElement(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        final String name = Json.reqStr(args, "name");
        RowSet rowSet = new RowSet(ops.engine, q, new Attribute[]{});
        try {
            final Row row = findRow(rowSet, Json.reqStr(args, "element"), "element");
            final String old = row.getName();
            ops.inTransaction(new RamusBridge.Task<Object>() {
                public Object run() {
                    row.setName(name);
                    return null;
                }
            });
            Map<String, Object> m = Json.obj();
            m.put("id", Long.valueOf(row.getElementId()));
            m.put("name", name);
            m.put("previous_name", old);
            m.put("classifier", q.getName());
            return m;
        } finally {
            rowSet.close();
        }
    }

    static Map<String, Object> deleteElement(final RamusBridge.Ops ops, Map<String, Object> args) throws Exception {
        ops.requireOpen();
        Qualifier q = Resolve.classifier(ops.engine, Json.reqStr(args, "classifier"));
        final RowSet rowSet = new RowSet(ops.engine, q, new Attribute[]{});
        try {
            final Row row = findRow(rowSet, Json.reqStr(args, "element"), "element");
            final long id = row.getElementId();
            final String name = row.getName();
            ops.inTransaction(new RamusBridge.Task<Object>() {
                public Object run() {
                    rowSet.deleteRow(row);
                    return null;
                }
            });
            Map<String, Object> m = Json.obj();
            m.put("deleted", Boolean.TRUE);
            m.put("id", Long.valueOf(id));
            m.put("name", name);
            m.put("classifier", q.getName());
            return m;
        } finally {
            rowSet.close();
        }
    }

    private static Row findRow(RowSet rowSet, String selector, String argName) {
        selector = selector.trim();
        List<Row> rows = rowSet.getAllRows();
        for (Row row : rows) {
            if (selector.equals(Long.toString(row.getElementId()))) {
                return row;
            }
        }
        List<Row> matches = new ArrayList<Row>();
        for (Row row : rows) {
            if (selector.equalsIgnoreCase(row.getName())) {
                matches.add(row);
            }
        }
        if (matches.size() == 1) {
            return matches.get(0);
        }
        if (matches.size() > 1) {
            throw new IllegalArgumentException("'" + selector + "' matches " + matches.size()
                    + " elements; use the numeric id from 'element list'");
        }
        throw new IllegalArgumentException("No element with id or name '" + selector + "' (" + argName + ")");
    }
}
