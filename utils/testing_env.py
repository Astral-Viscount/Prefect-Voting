import os
from dotenv import find_dotenv, load_dotenv

load_dotenv(override=True)

print("current working directory:", os.getcwd())
print(".env location:", find_dotenv())
print("school domain:", os.getenv("SCHOOL_DOMAIN"))