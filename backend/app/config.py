from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
env_path = PROJECT_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = (
        "postgresql://postgres:secretpassword@localhost:5432/app"
    )

    GOOGLE_MAPS_API_KEY: str = ""
    FIREBASE_PROJECT_ID: str = "hanoi-policy-makers"
    FIREBASE_STORAGE_BUCKET: str = "hanoi-policy-makers.firebasestorage.app"
    FIREBASE_SERVICE_ACCOUNT_PATH: Path | None = None
    FIREBASE_SERVICE_ACCOUNT_JSON: str = ""
    FIRESTORE_SURVEY_COLLECTION: str = "survey_submissions"
    FIRESTORE_PROFILE_COLLECTION: str = "user_profiles"
    FIRESTORE_BASELINE_COLLECTION: str = "baseline_rows"
    USE_FIRESTORE_BASELINE: bool = False

    ARTIFACT_DIR: Path = BACKEND_DIR / "artifacts"
    DATASET_DIR: Path = BACKEND_DIR / "datasets"
    WEIGHTS_DIR: Path = BACKEND_DIR / "weights"
    MODEL_WEIGHT_DIR: Path = WEIGHTS_DIR / "model_lab" / "default"
    MODEL_RUN_DIR: Path = WEIGHTS_DIR / "model_lab" / "runs"
    K_MEDIAN_WEIGHT_DIR: Path = WEIGHTS_DIR / "kmedian" / "default"
    K_MEDIAN_RUN_DIR: Path = WEIGHTS_DIR / "kmedian" / "runs"
    STATION_CACHE_FILE: Path = BACKEND_DIR / "artifacts" / "stations.json"
    DISTRICT_CENTER_CACHE_FILE: Path = BACKEND_DIR / "artifacts" / "district_centers.json"
    HANOI_BOUNDARY_CACHE_FILE: Path = BACKEND_DIR / "artifacts" / "hanoi_district_boundaries.json"
    SURVEY_FALLBACK_FILE: Path = BACKEND_DIR / "datasets" / "baseline.csv"
    POLICY_DASHBOARD_FILE: Path = BACKEND_DIR / "datasets" / "baseline.csv"

    # Gemini is used for optional model and chart explanations. Keep the key
    # on the backend; it is never returned to the browser.
    GEMINI_API_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    CORS_ALLOW_ORIGINS: str = "*"

    SURVEY_TABLE: str = "travel_survey"
    DISTRICT_TABLE: str = "districts"

    MAX_TRAINING_ROWS: int = 100_000
    MAX_K_MEDIAN_ROWS: int = 500
    K_MEDIAN_TIME_LIMIT_SECONDS: int = 300

    STATION_CAPACITY: int = 20
    MAX_STATION_CANDIDATES: int = 300
    RANDOM_SEED: int = 42

    GAS_PRICE_PER_LITER: float = 23000.0
    ICE_MOTO_KM_PER_LITER: float = 45.0
    ICE_MOTO_MAINTENANCE_PER_KM: float = 200.0
    ICE_MOTO_INSURANCE_MONTHLY: float = 10000.0

    ELECTRICITY_KWH_PRICE: float = 2500.0
    EV_MOTO_KWH_PER_100KM: float = 3.0
    EV_DEFAULT_MONTHLY_LOAN: float = 500000.0

    DEFAULT_PUBLIC_TRANSIT_FARE: float = 8000.0
    WEEKS_PER_MONTH: float = 4.33

    ICE_MOTO_CO2_PER_KM: float = 65.0
    BUS_CO2_PER_PASSENGER_KM: float = 28.0
    EV_MOTO_CO2_PER_KM: float = 18.0

    @model_validator(mode="after")
    def resolve_relative_paths(self):
        path_fields = [
            "ARTIFACT_DIR", "DATASET_DIR", "WEIGHTS_DIR",
            "MODEL_WEIGHT_DIR", "MODEL_RUN_DIR", "K_MEDIAN_WEIGHT_DIR",
            "K_MEDIAN_RUN_DIR", "STATION_CACHE_FILE",
            "DISTRICT_CENTER_CACHE_FILE", "HANOI_BOUNDARY_CACHE_FILE",
            "SURVEY_FALLBACK_FILE", "POLICY_DASHBOARD_FILE",
        ]
        if self.FIREBASE_SERVICE_ACCOUNT_PATH:
            service_account_path = Path(self.FIREBASE_SERVICE_ACCOUNT_PATH)
            if not service_account_path.is_absolute():
                service_account_path = PROJECT_DIR / service_account_path
            self.FIREBASE_SERVICE_ACCOUNT_PATH = service_account_path.resolve()
        for field_name in path_fields:
            path = Path(getattr(self, field_name))
            if not path.is_absolute():
                path = BACKEND_DIR / path
            setattr(self, field_name, path.resolve())
        return self

    model_config = SettingsConfigDict(
        env_file=str(env_path),
        extra="allow",
    )


settings = Settings()
