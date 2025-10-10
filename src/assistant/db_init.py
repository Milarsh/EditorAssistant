def main():
    from .db import create_schema
    create_schema()
    print("DB schema is ready.")

if __name__ == "__main__":
    main()
