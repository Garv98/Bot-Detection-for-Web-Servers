
# BotDefense_BigData: High-Availability Bot Mitigation Platform

## 1. Project Overview
This project implements a **Lambda-Architecture** inspired Bot Detection system. It leverages **Apache Spark** for massive historical log analysis and **Apache Cassandra** for real-time state management and mitigation.

## 2. Architecture
- **Batch Layer (PySpark):** Processes `public_v2.json` (3GB) to extract behavioral features (req_count, interval_avg, interval_std).
- **ML Layer (Scikit-Learn):** Trains a Random Forest model on behavioral data to distinguish humans from bots.
- **Speed Layer (Cassandra):** Stores IP profiles with a 24-hour TTL for sub-millisecond real-time lookups.
- **Serving Layer (FastAPI):** Intercepts requests, queries Cassandra, executes inference, and throttles bots.

## 3. Directory Structure
- `src/pyspark_etl.py`: Spark processing script.
- `src/train_model.py`: Model training script.
- `src/cassandra_client.py`: Cassandra NoSQL interface.
- `server.py`: FastAPI server with Bot Defense Middleware.
- `index.html`: WebSocket-enabled Monitoring Dashboard.
- `docker-compose.yml`: Launches the Cassandra cluster.

## 4. Setup Instructions
1. **Infrastructure:**
   ```bash
   docker-compose up -d
   ```
2. **Dependencies:**
   ```bash
   pip install pyspark cassandra-driver fastapi uvicorn pandas scikit-learn joblib httpx
   ```
3. **ETL Pipeline:**
   ```bash
   python src/pyspark_etl.py
   ```
4. **Train Model:**
   ```bash
   python src/train_model.py
   ```
5. **Start Server:**
   ```bash
   python server.py
   ```

## 5. Objectives
- Demonstrate **Scalable Data Engineering** using Spark.
- Implement **Low-Latency NoSQL Storage** using Cassandra.
- Apply **Behavioral Machine Learning** for cybersecurity.
- Provide **Real-time Observability** through WebSockets.
