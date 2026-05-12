
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window
import sys

def run_etl(input_path, output_path):
    # Initialize Spark Session
    spark = SparkSession.builder \
        .appName("BotDefense_ETL") \
        .config("spark.driver.memory", "4g") \
        .getOrCreate()

    print(f"Reading Big Data source: {input_path}")
    # Read the 3GB JSON file in a distributed manner
    df = spark.read.json(input_path)

    # Big Data Transformation: Feature Engineering
    # We use Window functions to calculate the interval between requests per IP
    windowSpec = Window.partitionBy("ip").orderBy("timestamp")
    
    df_transformed = df.withColumn("timestamp_sec", F.unix_timestamp(F.col("timestamp"))) \
                       .withColumn("prev_ts", F.lag("timestamp_sec").over(windowSpec)) \
                       .withColumn("interval", F.col("timestamp_sec") - F.col("prev_ts"))

    # Aggregating Behavioral Metrics
    print("Aggregating metrics per IP address...")
    features = df_transformed.groupBy("ip").agg(
        F.count("*").alias("req_count"),
        F.avg("interval").alias("avg_interval"),
        F.stddev("interval").alias("std_interval"),
        # Use User-Agent as a Ground Truth indicator for the training set
        F.max(F.when(F.lower(F.col("useragent")).contains("bot"), 1).otherwise(0)).alias("label")
    ).fillna(0)

    # Save to CSV for the Model Trainer
    print(f"Saving engineered features to {output_path}")
    features.coalesce(1).write.csv(output_path, header=True, mode="overwrite")
    
    spark.stop()

if __name__ == "__main__":
    # Point to the dataset in the parent directory
    run_etl("../public_v2.json", "data/processed_features")
