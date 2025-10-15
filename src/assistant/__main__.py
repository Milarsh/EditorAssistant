from db_init import db_init
from .server import server_init

def main():
    db_init()
    server_init()

if __name__ == "__main__":
    main()