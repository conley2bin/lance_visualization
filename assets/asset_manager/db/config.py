"""
Database configuration module
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', '192.168.10.222'),
    'port': os.getenv('DB_PORT', '15432'),
    'database': os.getenv('DB_NAME', 'dex_database'),
    'user': os.getenv('DB_USER', 'admin'),
    'password': os.getenv('DB_PASSWORD', 'dexrobot2024^')
}
