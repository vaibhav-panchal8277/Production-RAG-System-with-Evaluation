import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// Optional shared-secret header. The backend only enforces it when RAG_API_KEY
// is set server-side, so leaving this unset keeps local dev working.
// NOTE: anything in REACT_APP_* is baked into the client bundle and is visible
// to anyone who loads the page — this is a deployment convenience for a trusted
// network, not a substitute for real per-user auth.
const API_KEY = process.env.REACT_APP_RAG_API_KEY || "";

const http = axios.create({
  baseURL: API,
  timeout: 300_000,
  headers: API_KEY ? { "X-API-Key": API_KEY } : {},
});

export const api = {
  health: () => http.get("/health").then((r) => r.data),
  listDocs: () => http.get("/documents").then((r) => r.data),
  seedDocs: () => http.post("/documents/seed").then((r) => r.data),
  uploadDoc: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    // Per-request headers replace the instance defaults, so re-send the key.
    return http
      .post("/documents/upload", fd, {
        headers: {
          "Content-Type": "multipart/form-data",
          ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        },
      })
      .then((r) => r.data);
  },
  deleteDoc: (source) =>
    http.delete(`/documents/${encodeURIComponent(source)}`).then((r) => r.data),
  query: (body) => http.post("/query", body).then((r) => r.data),
  listConversations: (limit = 50) =>
    http.get("/conversations", { params: { limit } }).then((r) => r.data),
  getConversation: (id) => http.get(`/conversations/${id}`).then((r) => r.data),
  testset: () => http.get("/testset").then((r) => r.data),
  runEval: (body) => http.post("/evaluations/run", body).then((r) => r.data),
  listEvals: (limit = 30) =>
    http.get("/evaluations", { params: { limit } }).then((r) => r.data),
};
