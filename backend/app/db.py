from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_geocode_cache():
    """Initialize the geocode cache table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                id BIGSERIAL PRIMARY KEY,
                latitude_rounded NUMERIC(6, 4) NOT NULL,
                longitude_rounded NUMERIC(7, 4) NOT NULL,
                district_name TEXT,
                province_name TEXT,
                formatted_address TEXT,
                place_id TEXT,
                raw_response JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(latitude_rounded, longitude_rounded)
            );
        """))
        conn.commit()


def init_survey_submissions_table():
    """Initialize the survey submissions table if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS survey_submissions (
                id BIGSERIAL PRIMARY KEY,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                source VARCHAR(50) NOT NULL DEFAULT 'web'
            );
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_survey_submissions_created_at
            ON survey_submissions(created_at);
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_survey_submissions_payload
            ON survey_submissions
            USING GIN(payload);
        """))

        conn.execute(text("""
            ALTER TABLE survey_submissions
            ADD COLUMN IF NOT EXISTS owner_sub TEXT,
            ADD COLUMN IF NOT EXISTS owner_email TEXT;
        """))

        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_survey_submissions_owner_sub
            ON survey_submissions(owner_sub);
        """))

        conn.commit()


def init_user_profiles_table():
    """Create local display-name and avatar overrides for Google users."""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                google_sub TEXT PRIMARY KEY,
                email TEXT,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        conn.commit()
