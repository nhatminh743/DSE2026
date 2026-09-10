import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

# Database connection URL
DB_URL = "postgresql://postgres:secretpassword@localhost:5432/app"
engine = create_engine(DB_URL)

csv_file = r"C:\Users\ACER\Downloads\497us-osfstorage-archive\data\hn_survey_26k.csv"
df = pd.read_csv(csv_file, na_values=["NA", "N/A", "null", ""])

# Drop extra non-schema columns if present
if "index" in df.columns:
    df = df.drop(columns=["index"], errors="ignore")

# Lowercase all column headers
df.columns = [col.strip().lower() for col in df.columns]

# Ensure string handling for ownership columns containing non-numeric values (e.g. 'more_5')
string_cols = ["own_car", "own_motob", "own_ebike", "own_bike"]
for col in string_cols:
    if col in df.columns:
        df[col] = df[col].astype(str).replace({"nan": None, "None": None, "<NA>": None})

# Convert remaining NaN values to None for SQL NULL insertion
df = df.replace({np.nan: None})

# Insert rows into travel_survey
print("Uploading rows to 'travel_survey' table...")
df.to_sql("travel_survey", con=engine, if_exists="append", index=False)
print(f"Successfully uploaded {len(df)} rows!")

# Populate PostGIS geography points
print("Generating PostGIS points...")
with engine.begin() as conn:
    conn.execute(text("""
        UPDATE travel_survey
        SET orig_geom = ST_SetSRID(ST_MakePoint(origlon, origlat), 4326)::geography
        WHERE origlon IS NOT NULL AND origlat IS NOT NULL;

        UPDATE travel_survey
        SET dest_geom = ST_SetSRID(ST_MakePoint(destlon, destlat), 4326)::geography
        WHERE destlon IS NOT NULL AND destlat IS NOT NULL;
    """))

print("PostGIS geometries successfully populated!")