from src.db.db import schema_exists, create_schema
from sqlalchemy.exc import OperationalError, ProgrammingError
import src.db.models.article_social_stat  # ensure model is registered
import src.db.models.article_social_stat_history  # ensure model is registered

def schema_init():
    try:
        if schema_exists():
            print("DB schema already exists")
        else:
            create_schema()
            print("DB schema created")
    except OperationalError as error:
        print(f"DB schema is not ready: {error}")
    except ProgrammingError as error:
        print(f"DB schema init programming error: {error}")
    except Exception as exception:
        print(f"DB schema init unexpected error: {exception}")