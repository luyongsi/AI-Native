"""Seed test data into knowledge_chunks for Context Builder testing."""
import uuid
import psycopg2
from embedder import get_embedder

e = get_embedder()
conn = psycopg2.connect(host="localhost", port=5432, database="ai_native", user="ai_native", password="ai_native_dev")
cur = conn.cursor()

test_data = [
    ("doc-001", "Python async patterns", "async def fetch_data(url):\n    async with aiohttp.ClientSession() as session:\n        async with session.get(url) as resp:\n            return await resp.json()", "code", "src/fetch.py", "/repo/app", "async python"),
    ("doc-002", "React component example", "export function DataTable({ rows, columns }: Props) {\n  const [sort, setSort] = useState(null);\n  return <table className='natural-width'>{rows.map(r => <tr>{columns.map(c => <td>{r[c]}</td>)}</tr>)}</table>\n}", "code", "src/ui/table.tsx", "/repo/app", "react component"),
    ("doc-003", "API design spec", "The Context Builder API provides POST /context/build for assembling context packages based on agent type and task parameters.", "spec", "", "", "api spec context"),
    ("doc-004", "Deployment guide", "To deploy the ai-native stack, use docker-compose up -d from /opt/ai-native/. Ensure PostgreSQL is configured.", "knowledge", "", "", "deploy guide"),
    ("doc-005", "Error handling patterns", "Use Result<T, E> pattern for all service operations. Never throw from service layer.", "knowledge", "", "", "error pattern"),
    ("doc-006", "Agent A9 behavior spec", "A9 is the code generation agent. It takes requirements and produces production-ready code with tests.", "spec", "", "", "agent a9 spec"),
    ("doc-007", "Database migrations guide", "Apply database migrations using alembic upgrade head. Never edit migrations after they are merged to main.", "doc", "", "", "database migration"),
    ("doc-008", "Prototype dashboard UI", "Dashboard wireframe: top nav, sidebar with tabs, main content area with cards. Styled with Tailwind.", "prototype", "", "", "prototype dashboard"),
    ("doc-009", "Python class definition", "class ContextBuilder:\n    def __init__(self, db_config, embedder):\n        self.db_config = db_config\n        self.embedder = embedder\n\n    def build_context(self, target_agent, max_tokens=8000):\n        return self.selector.select(target_agent, max_tokens=max_tokens)", "code", "src/builder.py", "/repo/app", "builder python"),
    ("doc-010", "TypeScript interface", "interface AgentConfig {\n  id: string;\n  name: string;\n  contextTypes: string[];\n  maxTokens: number;\n}", "code", "src/types.ts", "/repo/app", "typescript interface"),
]

for (doc_id, title, content, doc_type, file_path, repo_path, project) in test_data:
    vec = e.embed(content)
    vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
    cur.execute(
        "INSERT INTO knowledge_chunks (id, doc_id, title, content, doc_type, file_path, repo_path, embedding, search_vector, project) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, to_tsvector('english', %s), %s)",
        (str(uuid.uuid4()), doc_id, title, content, doc_type, file_path, repo_path, vec_str, content, project)
    )

conn.commit()
cur.execute("SELECT count(*) FROM knowledge_chunks")
cnt = cur.fetchone()[0]
print(f"Inserted {len(test_data)} rows. Total rows now: {cnt}")

cur.execute("SELECT doc_type, count(*) FROM knowledge_chunks GROUP BY doc_type ORDER BY doc_type")
for row in cur.fetchall():
    print(f"  {row[0]:15s}: {row[1]}")

cur.close()
conn.close()
print("[OK] Seed complete")
