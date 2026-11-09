# Debug RAG project

- Active project: C:\Users\15853\DEBUG_RAG. The original project at
  C:\Users\15853\Documents\ChatGPT\Agent项目\debug-rag is a retained backup.
- Read README.md for the consolidated current implementation and verification status;
  docs/迁移与本轮验收-2026-11-02.md and docs/progress.md retain dated evidence.
  Architecture baseline: docs/原整体技术方案.md (future designs are not achievements).
- Current priority: engineering reliability and remote dense/sparse retrieval.
  Full conversation state/condition inheritance remains deferred.
- Use explicit Python modules, FastAPI, SQLite and Milvus; no LangChain/LangGraph or ES.
  Docker currently runs Milvus only. Preserve the existing data volume.
- Local bge-small + BM25 remains the default baseline. BGE-M3 runs remotely,
  never download or run it on this laptop. Real Viking encoding and isolated hybrid
  build/search passed on 2026-11-04; enhanced rewrite/rerank/generation was not enabled.
- Latest authorization (2026-11-03): user explicitly approved implementing DOCX/PDF
  parsing and real BGE-M3 calls within the existing total budget. Do not automatically
  enable other paid stages or transmit company documents. Global .env flags remain off;
  the explicit Viking verification script enables only its own process.
- All paid stages share one
  ledger and CNY 50/month limit using Asia/Shanghai calendar months.
- Historical Viking probes returned HTTP 403 / AccessDenied on 2026-11-03. The user
  opened the Beijing service and saved a new VikingDB Key on 2026-11-04; real probes
  and build/search then succeeded. Historical CNY 0.08 reservations remain unknown.
- Remote validation KB: demo-bge-m3-validation; published generation
  0a2ec48337f84fb6b0ef0a9e3430fd9b, 8 simulation docs, 34 vector windows, 529 sparse
  terms; dense Top5 + sparse Top5 -> one global RRF -> parent context passed.
  Existing KB pointers and .env switches remain unchanged. Build/probe reserved
  CNY 0.44 for 11 requests; this is not a provider invoice. Latest total project
  accounted upper bound CNY 0.569703. See docs/BGE-M3真实建库验收-2026-11-04.md.
- Files under note/ are user-supplied documents generated from company code, not
  simulation fixtures. They have only been inspected locally; parsing review,
  publication and permission for remote processing are still pending.
- DOCX/PDF extraction requires review before ingest; preserve binary originals and
  native source locators. OCR/visual semantic recognition is not implemented yet.
- Never print keys, raw provider errors or unredacted Settings inputs. Unit tests must
  isolate RAG_* environment variables and default dotenv. A previous legacy assertion
  exposed a credential; the user was told to rotate it. Never repeat its value.
- All current business fixtures are independent simulations. Do not claim company
  adoption, business accuracy or production benefit from them.
- Historical verification (2026-11-02): 188 offline unit tests, 2 real Milvus tests,
  four local HTTP cases, browser local build/source view and persisted stop/start.
- Latest verification (2026-11-04): 210 offline tests and 2 real Milvus tests passed;
  generated DOCX/PDF each passed extraction, review, SQLite persistence, local-model
  indexing and source-located retrieval; baseline search and both HTTP source
  endpoints passed after API startup. Baseline generation and paid-call count
  were unchanged. See docs/文档解析与远程编码验收-2026-11-04.md for boundaries.
  Do not report historical evidence as a new run or generated samples as business QA.
- Preserve source/revision/generation mapping and citation boundaries. Failed builds
  must retain the old published generation. Never clear collections on startup.
- Liveness is not readiness. Configuration is not a real provider test.
- Keep source, tests, docs, fixtures, infra, scripts, lockfile, config template,
  SQLite/WAL/SHM, index artifacts and budget/evidence records. Cache and disposable
  test output may be cleaned. Do not delete retained index generations as caches.
- Cleanup removed the migration development copy and one-time sync helpers; edit this
  active project directly under the applicable filesystem approval rules.
