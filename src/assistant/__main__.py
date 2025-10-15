from sqlalchemy.exc import OperationalError, ProgrammingError
from .server import main
from .db import create_schema, schema_exists

if __name__ == "__main__":
    try:
        if schema_exists():
            print("DB schema already exists")
        else:
            schema = create_schema()
            print("DB schema created")
    except OperationalError as error:
        print(f"DB schema is not ready: {error}")
    except ProgrammingError as error:
        print(f"DB schema init programming error: {error}")
    except Exception as exception:
        print(f"DB schema init unexpected error: {exception}")

    main()