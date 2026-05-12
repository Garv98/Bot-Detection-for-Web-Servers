
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib
import glob
import os

def train():
    # Spark output is a directory of CSVs, we find the one file
    path = "data/processed_features/*.csv"
    csv_files = glob.glob(path)
    if not csv_files:
        print("Error: No processed features found. Run pyspark_etl.py first.")
        return

    df = pd.read_csv(csv_files[0])
    
    # Select behavioral features
    X = df[['req_count', 'avg_interval', 'std_interval']]
    y = df['label']
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print("Training Behavioral Bot Classifier...")
    clf = RandomForestClassifier(n_estimators=100, random_state=42)
    clf.fit(X_train, y_train)
    
    print("\nModel Evaluation:")
    print(classification_report(y_test, clf.predict(X_test)))
    
    # Export for real-time serving
    joblib.dump(clf, "models/bot_model.pkl")
    print("\nModel exported to models/bot_model.pkl")

if __name__ == "__main__":
    train()
