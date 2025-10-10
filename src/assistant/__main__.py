from .server import main
from .db import create_schema

if __name__ == "__main__":
    create_schema()
    main()