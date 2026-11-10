from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from  config import DATABASE_URL
from sqlalchemy import text

Engine  = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=Engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Import your engine from the file where you defined it
# (Assuming it's in a file named database.py)

def check_connection():
    try:
        # Connect to the database and run a simple test query
        with Engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("✅ Database connection successful!")
    except Exception as e:
        print("❌ Database connection failed!")
        print(f"Error details: {e}")

if __name__ == "__main__":
    check_connection()
