// Real-time collaborative-document sync for the Drafting section.
//
// Yjs CRDT documents are synced over WebSockets via Hocuspocus. Every connection
// is authenticated with the tenant's own access JWT (same HS256 secret the Go
// gateway signs with), the document-level access rule mirrors the gateway
// (owner OR shared-with OR Managing Partner), and the merged CRDT state is
// persisted into the caller's tenant schema (`<schema>.collab_documents.ydoc`).

const { Server } = require("@hocuspocus/server");
const { Database } = require("@hocuspocus/extension-database");
const jwt = require("jsonwebtoken");
const { Pool } = require("pg");

const JWT_SECRET = process.env.JWT_SECRET || "dev-only-secret-change-me";
const PORT = parseInt(process.env.PORT || "3100", 10);

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: parseInt(process.env.PG_POOL_MAX || "10", 10),
});

// tenant schema name = "tenant_" + uuid with dashes stripped (matches the Go side).
// Validated against this exact shape before it is ever interpolated into SQL.
const SCHEMA_RE = /^tenant_[0-9a-f]{32}$/;
function schemaFor(tid) {
  return "tenant_" + String(tid || "").replace(/-/g, "").toLowerCase();
}

const server = Server.configure({
  name: "wakili-collab",
  port: PORT,

  // Runs on every incoming connection before the document is opened.
  async onAuthenticate({ token, documentName }) {
    let claims;
    try {
      claims = jwt.verify(token, JWT_SECRET);
    } catch (e) {
      throw new Error("invalid or expired token");
    }
    const schema = schemaFor(claims.tid);
    if (!SCHEMA_RE.test(schema)) {
      throw new Error("token is not bound to a tenant");
    }
    const senior = claims.role === "Managing Partner";
    const { rows } = await pool.query(
      `SELECT (d.owner_id = $1 OR $2
               OR EXISTS (SELECT 1 FROM "${schema}".collab_document_shares s
                          WHERE s.document_id = d.id AND s.user_id = $1)) AS ok
         FROM "${schema}".collab_documents d WHERE d.id = $3`,
      [claims.uid, senior, documentName]
    );
    if (!rows.length || !rows[0].ok) {
      throw new Error("no access to this document");
    }
    // Returned object becomes the connection `context`, passed to fetch/store
    // and broadcast (minus token) to peers for awareness/cursors.
    return {
      schema,
      userId: claims.uid,
      name: claims.name || claims.email || "Member",
    };
  },

  extensions: [
    new Database({
      // Load the stored Yjs state for a document from the caller's tenant schema.
      async fetch({ documentName, context }) {
        if (!context || !SCHEMA_RE.test(context.schema)) return null;
        const { rows } = await pool.query(
          `SELECT ydoc FROM "${context.schema}".collab_documents WHERE id = $1`,
          [documentName]
        );
        if (rows.length && rows[0].ydoc) {
          return new Uint8Array(rows[0].ydoc);
        }
        return null;
      },
      // Persist the merged CRDT state back to the tenant schema (debounced by Hocuspocus).
      async store({ documentName, state, context }) {
        if (!context || !SCHEMA_RE.test(context.schema)) return;
        await pool.query(
          `UPDATE "${context.schema}".collab_documents
              SET ydoc = $1, updated_at = now() WHERE id = $2`,
          [Buffer.from(state), documentName]
        );
      },
    }),
  ],
});

server.listen().then(() => {
  console.log(`[collab] Hocuspocus listening on :${PORT}`);
});
