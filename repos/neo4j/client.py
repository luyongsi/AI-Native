from neo4j import GraphDatabase

class Neo4jClient:
    def __init__(self, uri="bolt://localhost:7687", user="neo4j", password="password123"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def trace_downstream(self, api_path):
        """变更影响追溯：给定 API → 找到所有受影响的下游"""
        query = """
        MATCH (api:API {path: $path})<-[:CALLS]-(comp:Component)
        OPTIONAL MATCH (comp)<-[:COVERS]-(test:TestCase)
        RETURN api.path as api, collect(DISTINCT comp.name) as components,
               collect(DISTINCT test.id) as tests
        """
        with self.driver.session() as session:
            return session.run(query, path=api_path).single()

    def trace_upstream(self, api_path):
        """向上追溯：给定 API → 找到需求来源"""
        query = """
        MATCH (req:Requirement)-[:HAS_SPEC]->(spec:Spec)-[:DEFINES]->(api:API {path: $path})
        RETURN req.id as req_id, req.title as req_title, spec.id as spec_id, spec.version as spec_version
        """
        with self.driver.session() as session:
            return session.run(query, path=api_path).single()

    def knowledge_graph_health(self):
        """知识库覆盖度统计"""
        query = """
        MATCH (c:Component)
        OPTIONAL MATCH (c)-[:CALLS]->(a:API)
        OPTIONAL MATCH (c)<-[:COVERS]-(t:TestCase)
        RETURN c.type as type, count(c) as total,
               round(100.0 * count(a) / count(c)) as api_coverage,
               round(100.0 * count(t) / count(c)) as test_coverage
        """
        with self.driver.session() as session:
            return list(session.run(query))

    def change_impact(self, api_path):
        """变更影响分析：给定 API，找到所有 AFFECTS 关系"""
        query = """
        MATCH (api:API {path: $path})-[:AFFECTS]->(comp:Component)
        OPTIONAL MATCH (comp)-[:CALLS]->(other:API)
        RETURN api.path as api_path, comp.name as affected_component,
               collect(DISTINCT other.path) as also_calls
        """
        with self.driver.session() as session:
            return list(session.run(query, path=api_path))

    def agent_artifacts(self):
        """查看 Agent 产出物"""
        query = """
        MATCH (agent:Agent)-[:PRODUCED]->(artifact:Artifact)
        OPTIONAL MATCH (artifact)-[:CONTAINS]->(test:TestCase)
        RETURN agent.id as agent, agent.name as agent_name,
               artifact.type as artifact_type, artifact.name as artifact_name,
               collect(test.id) as contains_tests
        """
        with self.driver.session() as session:
            return list(session.run(query))

    def close(self):
        self.driver.close()
