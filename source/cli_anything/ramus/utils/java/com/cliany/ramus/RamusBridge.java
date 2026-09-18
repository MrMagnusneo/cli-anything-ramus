package com.cliany.ramus;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.PrintStream;
import java.io.StringWriter;
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.ramussoft.common.AccessRules;
import com.ramussoft.common.Attribute;
import com.ramussoft.common.AttributeType;
import com.ramussoft.common.Engine;
import com.ramussoft.common.Qualifier;
import com.ramussoft.common.journal.Journaled;
import com.ramussoft.core.impl.FileIEngineImpl;
import com.ramussoft.database.Database;
import com.ramussoft.database.FileDatabaseFactory;

/**
 * Headless JSON bridge to the real Ramus engine.
 *
 * <p>The process reads one JSON request object per line from stdin and writes
 * exactly one JSON response object per line to stdout:
 *
 * <pre>
 *   {"id": 1, "op": "model.list", "args": {}}
 *   {"id": 1, "ok": true, "result": {...}}
 * </pre>
 *
 * <p>Ramus itself prints to {@code System.out} in a few places, so the real
 * stdout is captured up front and {@code System.out} is redirected to stderr.
 * Only protocol frames ever reach the pipe the CLI reads.
 */
public class RamusBridge {

    public static final String BRIDGE_VERSION = "1.0.0";

    /** The real stdout, reserved for protocol frames. */
    private final PrintStream wire;

    private final Ops ops = new Ops();

    RamusBridge(PrintStream wire) {
        this.wire = wire;
    }

    public static void main(String[] args) throws Exception {
        System.setProperty("java.awt.headless", "true");
        System.setProperty("user.ramus.application.name", "cli-anything-ramus");

        OutputStream rawOut = new FileOutputStream(FileDescriptor.out);
        PrintStream wire = new PrintStream(rawOut, true, "UTF-8");
        // Everything Ramus prints goes to stderr; the pipe stays clean.
        System.setOut(new PrintStream(new FileOutputStream(FileDescriptor.err), true, "UTF-8"));

        RamusBridge bridge = new RamusBridge(wire);

        if (args.length > 0 && "--once".equals(args[0])) {
            // Single-request mode, used by diagnostics and by callers that do
            // not want to manage a long-lived process.
            BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
            String line = in.readLine();
            if (line != null) {
                bridge.handleLine(line);
            }
            bridge.ops.closeQuietly();
            return;
        }

        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        String line;
        while ((line = in.readLine()) != null) {
            if (line.trim().length() == 0) {
                continue;
            }
            if (!bridge.handleLine(line)) {
                break;
            }
        }
        bridge.ops.closeQuietly();
    }

    /** @return false when the peer asked the bridge to shut down. */
    private boolean handleLine(String line) {
        Object id = null;
        try {
            Map<String, Object> request = Json.asMap(Json.read(line));
            id = request.get("id");
            String op = Json.reqStr(request, "op");
            if ("shutdown".equals(op)) {
                respond(id, Json.obj());
                return false;
            }
            Map<String, Object> args = Json.asMap(request.get("args"));
            Object result = ops.dispatch(op, args);
            respond(id, result);
        } catch (Throwable t) {
            fail(id, t);
        }
        return true;
    }

    private void respond(Object id, Object result) {
        Map<String, Object> frame = Json.obj();
        frame.put("id", id);
        frame.put("ok", Boolean.TRUE);
        frame.put("result", result);
        wire.println(Json.write(frame));
        wire.flush();
    }

    private void fail(Object id, Throwable t) {
        Map<String, Object> frame = Json.obj();
        frame.put("id", id);
        frame.put("ok", Boolean.FALSE);
        String message = t.getMessage();
        if (message == null || message.length() == 0) {
            message = t.getClass().getName();
        }
        frame.put("error", message);
        frame.put("error_type", t.getClass().getName());
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        frame.put("trace", sw.toString());
        wire.println(Json.write(frame));
        wire.flush();
    }

    // ================================================================== ops

    /**
     * Holds the open project and applies operations to the live Ramus engine.
     */
    static final class Ops {

        File path;
        Database database;
        Engine engine;
        AccessRules rules;
        boolean modified;

        Object dispatch(String op, Map<String, Object> args) throws Exception {
            if ("ping".equals(op)) {
                return ping();
            }
            if ("project.new".equals(op)) {
                return ProjectOps.newProject(this, args);
            }
            if ("project.open".equals(op)) {
                return ProjectOps.open(this, args);
            }
            if ("project.save".equals(op)) {
                return ProjectOps.save(this, args);
            }
            if ("project.save-copy".equals(op)) {
                return ProjectOps.saveCopy(this, args);
            }
            if ("project.close".equals(op)) {
                return ProjectOps.close(this);
            }
            if ("project.info".equals(op)) {
                return ProjectOps.info(this);
            }

            if (op.startsWith("model.")) {
                return ModelOps.dispatch(this, op, args);
            }
            if (op.startsWith("function.")) {
                return FunctionOps.dispatch(this, op, args);
            }
            if (op.startsWith("arrow.")) {
                return ArrowOps.dispatch(this, op, args);
            }
            if (op.startsWith("classifier.") || op.startsWith("element.")) {
                return DataOps.dispatch(this, op, args);
            }
            if (op.startsWith("export.") || op.startsWith("import.")) {
                return ExportOps.dispatch(this, op, args);
            }
            throw new IllegalArgumentException("Unknown operation: " + op);
        }

        private Map<String, Object> ping() {
            Map<String, Object> m = Json.obj();
            m.put("bridge_version", BRIDGE_VERSION);
            m.put("java_version", System.getProperty("java.version"));
            m.put("java_vendor", System.getProperty("java.vendor"));
            m.put("headless", Boolean.valueOf(java.awt.GraphicsEnvironment.isHeadless()));
            m.put("project_open", Boolean.valueOf(engine != null));
            m.put("project_path", path == null ? null : path.getAbsolutePath());
            m.put("modified", Boolean.valueOf(modified));
            return m;
        }

        /** Fails loudly rather than silently no-op'ing on a closed project. */
        void requireOpen() {
            if (engine == null) {
                throw new IllegalStateException(
                        "No project is open. Open one first with: project open <file.rsf>");
            }
        }

        Journaled journal() {
            return (Journaled) engine;
        }

        /** Runs a mutation inside a Ramus user transaction, rolling back on error. */
        <T> T inTransaction(Task<T> task) throws Exception {
            requireOpen();
            Journaled j = journal();
            j.startUserTransaction();
            try {
                T result = task.run();
                j.commitUserTransaction();
                modified = true;
                return result;
            } catch (Throwable t) {
                try {
                    j.rollbackUserTransaction();
                } catch (Exception ignored) {
                    // The original failure is what the caller needs to see.
                }
                if (t instanceof Exception) {
                    throw (Exception) t;
                }
                throw new RuntimeException(t);
            }
        }

        void openFile(File file) throws Exception {
            closeQuietly();
            Database db = FileDatabaseFactory.createDatabase(file);
            this.database = db;
            this.engine = db.getEngine(null);
            this.rules = db.getAccessRules(null);
            this.path = file;
            this.modified = false;
        }

        void createEmpty() {
            closeQuietly();
            Database db = FileDatabaseFactory.createDatabase(null);
            this.database = db;
            this.engine = db.getEngine(null);
            this.rules = db.getAccessRules(null);
            this.path = null;
            this.modified = false;
        }

        String saveTo(File target) throws Exception {
            requireOpen();
            File parent = target.getAbsoluteFile().getParentFile();
            if (parent != null && !parent.isDirectory()) {
                if (!parent.mkdirs()) {
                    throw new java.io.IOException("Cannot create directory: " + parent);
                }
            }
            FileIEngineImpl impl = (FileIEngineImpl) engine.getDeligate();
            impl.saveToFile(target);
            this.path = target;
            this.modified = false;
            return target.getAbsolutePath();
        }

        void closeQuietly() {
            if (engine != null) {
                try {
                    FileIEngineImpl impl = (FileIEngineImpl) engine.getDeligate();
                    try {
                        if (engine instanceof Journaled) {
                            ((Journaled) engine).close();
                        }
                    } catch (Exception ignored) {
                        // Best effort; the process is about to drop the engine.
                    }
                    impl.close();
                } catch (Exception ignored) {
                    // Ditto.
                }
            }
            engine = null;
            rules = null;
            database = null;
            path = null;
            modified = false;
        }

        /**
         * Creates (or reuses) the shared "Name" text attribute that Ramus uses
         * as the display name of function and classifier elements.
         */
        Attribute nameAttribute() {
            for (Object o : engine.getAttributes()) {
                Attribute a = (Attribute) o;
                if ("Core.Text".equals(a.getAttributeType().toString()) && "Name".equals(a.getName())) {
                    return a;
                }
            }
            Attribute name = engine.createAttribute(new AttributeType("Core", "Text", true));
            name.setName("Name");
            engine.updateAttribute(name);
            return name;
        }
    }

    interface Task<T> {
        T run() throws Exception;
    }

    // ------------------------------------------------------------- utilities

    static List<Object> emptyList() {
        return new ArrayList<Object>();
    }

    static Map<String, Object> map() {
        return new LinkedHashMap<String, Object>();
    }

    static File resolve(String p) {
        return new File(p).getAbsoluteFile();
    }

    static FileInputStream openRead(File f) throws Exception {
        if (!f.isFile()) {
            throw new java.io.FileNotFoundException("File not found: " + f.getAbsolutePath());
        }
        return new FileInputStream(f);
    }

    static Qualifier requireQualifier(Qualifier q, String what) {
        if (q == null) {
            throw new IllegalArgumentException("No such " + what);
        }
        return q;
    }
}
