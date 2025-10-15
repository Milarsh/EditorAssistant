from src.db.db_init import schema_init
from src.assistant.server import server_init

def main():
    schema_init()
    server_init()

if __name__ == "__main__":
    main()