from dotenv import load_dotenv
import os

def load_config(prop_name):
    load_dotenv()
    return os.getenv(prop_name)