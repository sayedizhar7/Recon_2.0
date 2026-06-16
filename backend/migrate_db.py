import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(BASE_DIR, "recon.db"))

def migrate():
    if not os.path.exists(DB_PATH):
        print("Database not found, nothing to migrate.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE history_table ADD COLUMN mapping_json JSON")
        print("Successfully added mapping_json to history_table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column mapping_json already exists.")
        else:
            print(f"Error: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate()
