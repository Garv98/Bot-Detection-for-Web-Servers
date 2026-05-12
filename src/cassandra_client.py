
from cassandra.cluster import Cluster
import json
import time

class CassandraClient:
    def __init__(self, hosts=['127.0.0.1']):
        try:
            self.cluster = Cluster(hosts)
            self.session = self.cluster.connect()
            self._setup_schema()
            print("Connected to Apache Cassandra Feature Store.")
        except Exception as e:
            print(f"Cassandra Connection Error: {e}")
            self.session = None

    def _setup_schema(self):
        # Keyspace for Bot Defense
        self.session.execute("""
            CREATE KEYSPACE IF NOT EXISTS bot_defense 
            WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
        """)
        
        # Table for Real-time IP Profiles
        # Using TTL to automatically clear data for inactive IPs
        self.session.execute("""
            CREATE TABLE IF NOT EXISTS bot_defense.ip_profiles (
                ip text PRIMARY KEY,
                history text,
                risk_score float,
                last_updated timestamp
            )
        """)

    def get_profile(self, ip):
        if not self.session: return [], 0.0
        query = "SELECT history, risk_score FROM bot_defense.ip_profiles WHERE ip = %s"
        row = self.session.execute(query, (ip,)).one()
        if row:
            return json.loads(row.history), row.risk_score
        return [], 0.0

    def save_profile(self, ip, history, risk_score):
        if not self.session: return
        query = """
            INSERT INTO bot_defense.ip_profiles (ip, history, risk_score, last_updated)
            VALUES (%s, %s, %s, toTimestamp(now()))
            USING TTL 86400
        """
        self.session.execute(query, (ip, json.dumps(history[-50:]), risk_score))
