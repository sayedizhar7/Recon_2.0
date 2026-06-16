import subprocess
import os

env = os.environ.copy()
env['PGPASSWORD'] = '2003'

print("Setting up user...")
proc = subprocess.run([r'E:\Apps\PostgreSQL\bin\psql.exe', '-U', 'postgres', '-h', '127.0.0.1', '-c', "CREATE USER recon WITH PASSWORD 'recon';"], env=env, capture_output=True, text=True)
print("STDOUT:", proc.stdout)
print("STDERR:", proc.stderr)

print("Setting up database...")
proc2 = subprocess.run([r'E:\Apps\PostgreSQL\bin\psql.exe', '-U', 'postgres', '-h', '127.0.0.1', '-c', "CREATE DATABASE recon_db_local OWNER recon;"], env=env, capture_output=True, text=True)
print("STDOUT:", proc2.stdout)
print("STDERR:", proc2.stderr)
