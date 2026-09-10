import numpy as np
import pandas as pd
import pulp
from sklearn.cluster import KMeans
from sqlalchemy.orm import Session

from app.config import settings
from services.analytics import normalize_model_columns
from services.district_centers import assign_nearest_district
from services.survey_data import load_survey_dataframe


def haversine_matrix(
    people_coords: np.ndarray,
    station_coords: np.ndarray,
):
    """Calculate pairwise distances in kilometers."""
    people_rad = np.radians(people_coords)
    station_rad = np.radians(station_coords)

    person_lat = people_rad[:, 0][:, None]
    person_lon = people_rad[:, 1][:, None]
    station_lat = station_rad[:, 0][None, :]
    station_lon = station_rad[:, 1][None, :]

    delta_lat = station_lat - person_lat
    delta_lon = station_lon - person_lon
    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(person_lat)
        * np.cos(station_lat)
        * np.sin(delta_lon / 2) ** 2
    )

    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def _format_kmedian_solution(
    df_locations: pd.DataFrame,
    selected_stations: list[int],
    assigned_station_positions: np.ndarray,
    assigned_distances: np.ndarray,
    k_stations: int,
    solver_status: str,
    solver_method: str,
):
    coords = df_locations[["origlat", "origlon"]].to_numpy(dtype=float)
    weights = df_locations["weight"].to_numpy(dtype=float)
    num_nodes = len(coords)
    assignments = []
    district_names = (
        df_locations["district_name"].fillna("Unknown").astype(str).to_numpy()
        if "district_name" in df_locations.columns
        else np.full(num_nodes, "Unknown")
    )

    for i, station_position in enumerate(assigned_station_positions):
        station_index = selected_stations[int(station_position)]
        assignments.append({
            "person_index": int(i),
            "station_index": int(station_index),
            "person_lat": float(coords[i, 0]),
            "person_lon": float(coords[i, 1]),
            "station_lat": float(coords[station_index, 0]),
            "station_lon": float(coords[station_index, 1]),
            "district_name": str(district_names[i]),
            "weight": float(weights[i]),
            "distance_km": round(float(assigned_distances[i]), 3),
        })

    stations = []
    for station_index in selected_stations:
        station_assignments = [
            item for item in assignments
            if item["station_index"] == station_index
        ]
        stations.append({
            "station_index": int(station_index),
            "source_row_index": int(station_index),
            "lat": float(coords[station_index, 0]),
            "lon": float(coords[station_index, 1]),
            "district_name": str(district_names[station_index]),
            "assigned_people": len(station_assignments),
            "capacity": None,
            "total_weight": round(
                sum(item["weight"] for item in station_assignments),
                3,
            ),
        })

    return {
        "status": solver_status,
        "solver_method": solver_method,
        "objective_weighted_km": round(float(np.sum(weights * assigned_distances)), 3),
        "stations": stations,
        "assignments": assignments,
        "num_people": num_nodes,
        "num_stations": len(selected_stations),
        "requested_k": k_stations,
        "eligible_people": int(df_locations.attrs.get("eligible_people", num_nodes)),
        "sample_percent": float(df_locations.attrs.get("sample_percent", 100)),
    }


def _run_approximate_k_median(df_locations: pd.DataFrame, k_stations: int):
    """Scalable weighted medoid approximation for samples above the ILP limit."""
    coords = df_locations[["origlat", "origlon"]].to_numpy(dtype=float)
    weights = df_locations["weight"].to_numpy(dtype=float)
    clustering = KMeans(
        n_clusters=k_stations,
        random_state=settings.RANDOM_SEED,
        n_init=10,
    )
    labels = clustering.fit_predict(coords, sample_weight=weights)
    selected_stations = []
    for cluster_index in range(k_stations):
        member_indices = np.flatnonzero(labels == cluster_index)
        member_coords = coords[member_indices]
        member_weights = weights[member_indices]
        if len(member_indices) <= settings.MAX_K_MEDIAN_ROWS:
            local_distances = haversine_matrix(member_coords, member_coords)
            costs = (member_weights[:, None] * local_distances).sum(axis=0)
            selected_stations.append(int(member_indices[int(np.argmin(costs))]))
        else:
            centroid = clustering.cluster_centers_[cluster_index][None, :]
            distances = haversine_matrix(member_coords, centroid)[:, 0]
            selected_stations.append(int(member_indices[int(np.argmin(distances))]))

    distance_matrix = haversine_matrix(coords, coords[selected_stations])
    assigned_positions = np.argmin(distance_matrix, axis=1)
    assigned_distances = distance_matrix[np.arange(len(coords)), assigned_positions]
    return _format_kmedian_solution(
        df_locations,
        selected_stations,
        assigned_positions,
        assigned_distances,
        k_stations,
        "Approximate",
        "weighted_k_medoids_heuristic",
    )


def run_k_median_model(
    df_locations: pd.DataFrame,
    k_stations: int = 100,
):
    """Run exact k-median for small samples and a scalable medoid heuristic otherwise."""
    coords = df_locations[["origlat", "origlon"]].to_numpy(dtype=float)
    weights = df_locations["weight"].to_numpy(dtype=float)
    num_nodes = len(coords)

    if num_nodes == 0:
        return {
            "status": "Empty",
            "solver_method": "none",
            "objective_weighted_km": 0.0,
            "stations": [],
            "assignments": [],
            "num_people": 0,
            "num_stations": 0,
            "requested_k": k_stations,
            "eligible_people": int(df_locations.attrs.get("eligible_people", 0)),
            "sample_percent": float(df_locations.attrs.get("sample_percent", 100)),
        }

    k_stations = min(max(k_stations, 1), num_nodes)
    if num_nodes > settings.MAX_K_MEDIAN_ROWS:
        return _run_approximate_k_median(df_locations, k_stations)

    dist_mat = haversine_matrix(coords, coords)
    problem = pulp.LpProblem("k_Median_Ebike_Stations", pulp.LpMinimize)
    station_open = pulp.LpVariable.dicts("Station", range(num_nodes), cat="Binary")
    assignment = pulp.LpVariable.dicts(
        "Assign",
        [(i, j) for i in range(num_nodes) for j in range(num_nodes)],
        cat="Binary",
    )
    problem += pulp.lpSum(
        weights[i] * dist_mat[i, j] * assignment[i, j]
        for i in range(num_nodes)
        for j in range(num_nodes)
    )
    problem += pulp.lpSum(station_open[j] for j in range(num_nodes)) == k_stations
    for i in range(num_nodes):
        problem += pulp.lpSum(assignment[i, j] for j in range(num_nodes)) == 1
        for j in range(num_nodes):
            problem += assignment[i, j] <= station_open[j]

    problem.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=settings.K_MEDIAN_TIME_LIMIT_SECONDS))
    solver_status = pulp.LpStatus[problem.status]
    if solver_status not in {"Optimal", "Integer Feasible"}:
        raise RuntimeError(f"K-median model status: {solver_status}")

    selected_stations = [j for j in range(num_nodes) if pulp.value(station_open[j]) > 0.5]
    station_position = {station_index: index for index, station_index in enumerate(selected_stations)}
    assigned_positions = np.zeros(num_nodes, dtype=int)
    assigned_distances = np.zeros(num_nodes, dtype=float)
    for i in range(num_nodes):
        for j in selected_stations:
            if pulp.value(assignment[i, j]) > 0.5:
                assigned_positions[i] = station_position[j]
                assigned_distances[i] = dist_mat[i, j]
                break
    return _format_kmedian_solution(
        df_locations,
        selected_stations,
        assigned_positions,
        assigned_distances,
        k_stations,
        solver_status,
        "exact_ilp",
    )


def fetch_ebike_locations(
    db: Session,
    district_centers: list[dict],
    max_rows: int | None = None,
    sample_percent: float = 100,
):
    dataframe = normalize_model_columns(
        load_survey_dataframe(db=db, max_rows=settings.MAX_TRAINING_ROWS)
    )
    if not {"origlat", "origlon"}.issubset(dataframe.columns):
        return pd.DataFrame()
    main_mode = dataframe.get("vehic", pd.Series("", index=dataframe.index)).astype(str).str.strip().str.casefold()
    alt_ebike = pd.to_numeric(
        dataframe.get("alt_ebike", pd.Series(0, index=dataframe.index)),
        errors="coerce",
    ).fillna(0)
    df = dataframe[main_mode.eq("ebike") | alt_ebike.eq(1)].copy()
    df["origlat"] = pd.to_numeric(df["origlat"], errors="coerce")
    df["origlon"] = pd.to_numeric(df["origlon"], errors="coerce")
    df = df.dropna(subset=["origlat", "origlon"])
    eligible_people = len(df)
    sample_percent = min(100.0, max(1.0, float(sample_percent)))
    sample_size = max(1, int(round(eligible_people * sample_percent / 100))) if eligible_people else 0
    if sample_size < eligible_people:
        df = df.sample(n=sample_size, random_state=settings.RANDOM_SEED)
    if max_rows is not None and len(df) > max_rows:
        df = df.sample(n=max_rows, random_state=settings.RANDOM_SEED)
    df = assign_nearest_district(df, district_centers)

    weight_mapping = {
        "1_3": 1,
        "4_7": 2,
        "8_10": 3,
        "11_13": 4,
        "14_16": 5,
        "17_20": 6,
        "more_20": 7,
    }
    if "freqpweek" in df.columns:
        numeric_frequency = pd.to_numeric(df["freqpweek"], errors="coerce")
        df["weight"] = numeric_frequency.fillna(df["freqpweek"].map(weight_mapping)).fillna(1)
    else:
        df["weight"] = 1

    result = df.dropna(
        subset=["origlat", "origlon"],
    ).reset_index(drop=True)
    result.attrs["eligible_people"] = eligible_people
    result.attrs["sample_percent"] = sample_percent
    result.attrs["sampled_people"] = len(result)
    result.attrs["eligibility_rule"] = "vehic == ebike OR alt_ebike == 1"
    return result


def get_ebike_eligibility(db: Session) -> dict:
    dataframe = normalize_model_columns(
        load_survey_dataframe(db=db, max_rows=settings.MAX_TRAINING_ROWS)
    )
    if not {"origlat", "origlon"}.issubset(dataframe.columns):
        return {"eligible_people": 0, "source": dataframe.attrs.get("source", "unknown")}
    main_mode = dataframe.get("vehic", pd.Series("", index=dataframe.index)).astype(str).str.strip().str.casefold()
    alt_ebike = pd.to_numeric(
        dataframe.get("alt_ebike", pd.Series(0, index=dataframe.index)), errors="coerce"
    ).fillna(0)
    eligible = dataframe[main_mode.eq("ebike") | alt_ebike.eq(1)].copy()
    eligible["origlat"] = pd.to_numeric(eligible["origlat"], errors="coerce")
    eligible["origlon"] = pd.to_numeric(eligible["origlon"], errors="coerce")
    eligible = eligible.dropna(subset=["origlat", "origlon"])
    return {
        "eligible_people": int(len(eligible)),
        "total_survey_rows": int(len(dataframe)),
        "source": dataframe.attrs.get("source", "unknown"),
        "eligibility_rule": "Main mode is e-bike or alt_ebike is true",
        "exact_solver_limit": settings.MAX_K_MEDIAN_ROWS,
    }
