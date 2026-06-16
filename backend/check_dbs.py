import psycopg2
import sys

def check(host):
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user="recon",
            password="recon",
            host=host,
            port="5432"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT datname FROM pg_database;")
        dbs = cursor.fetchall()
        print(f"Databases found on {host}:5432:")
        for db in dbs:
            print(f" - {db[0]}")
        conn.close()
    except Exception as e:
        print(f"Error on {host}:", e)

check("127.0.0.1")
# We know the work server IP is 192.168.202.135 but let's test if we can reach it
check("192.168.202.135")
