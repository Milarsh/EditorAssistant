from db import schema_exists, create_schema
from sqlalchemy.exc import OperationalError, ProgrammingError

def db_init():
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