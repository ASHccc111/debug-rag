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
  never download or run it on this laptop. Remote implementation is mock-tested,
  not verified against the real provider.
- No new paid calls are authorized. Keep migrated external-call/rewrite/rerank flags
  off unless the user explicitly changes authorization. All paid stages share one
  ledger and CNY 50/month limit using Asia/Shanghai calendar months.
- Never print keys, raw provider errors or unredacted Settings inputs. Unit tests must
  isolate RAG_* environment variables and default dotenv. A previous legacy assertion
  exposed a credential; the user was told to rotate it. Never repeat its value.
- All current business fixtures are independent simulations. Do not claim company
  adoption, business accuracy or production benefit from them.
- Verified increment: 188 offline unit tests, 2 real Milvus tests, four local HTTP
  cases, browser local build/source view and actual stop/start with persisted state.
  Reuse historical evidence with dates; do not report it as a new test run.
- Preserve source/revision/generation mapping and citation boundaries. Failed builds
  must retain the old published generation. Never clear collections on startup.
- Liveness is not readiness. Configuration is not a real provider test.
- Keep source, tests, docs, fixtures, infra, scripts, lockfile, config template,
  SQLite/WAL/SHM, index artifacts and budget/evidence records. Cache and disposable
  test output may be cleaned. Do not delete retained index generations as caches.
- Cleanup removed the migration development copy and one-time sync helpers; edit this
  active project directly under the applicable filesystem approval rules.
