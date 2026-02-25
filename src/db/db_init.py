from src.db.db import schema_exists, create_schema
from sqlalchemy.exc import OperationalError, ProgrammingError
import src.db.models.article
import src.db.models.article_key_word
import src.db.models.article_social_stat
import src.db.models.article_social_stat_history
import src.db.models.article_stat
import src.db.models.article_stop_word
import src.db.models.auth_code
import src.db.models.key_word
import src.db.models.rubric
import src.db.models.session
import src.db.models.settings
import src.db.models.source
import src.db.models.stop_category
import src.db.models.stop_word
import src.db.models.user

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