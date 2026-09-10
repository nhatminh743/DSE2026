from app.config import settings

def calculate_modes(
    driving_data: dict, 
    transit_data: dict, 
    trips_per_week: float, 
    ev_loan_override: float = None
):
    weeks = settings.WEEKS_PER_MONTH
    monthly_trips = trips_per_week * weeks
    distance_km = driving_data["distance_km"]
    monthly_km = distance_km * monthly_trips

    # 1. OPTION 1: ICE Motorbike
    ice_fuel_cost = (monthly_km / settings.ICE_MOTO_KM_PER_LITER) * settings.GAS_PRICE_PER_LITER
    ice_maint_cost = monthly_km * settings.ICE_MOTO_MAINTENANCE_PER_KM
    ice_insurance = settings.ICE_MOTO_INSURANCE_MONTHLY
    ice_total_cost = ice_fuel_cost + ice_maint_cost + ice_insurance
    ice_time_hours = (driving_data["duration_mins"] * monthly_trips) / 60.0
    ice_co2_kg = (monthly_km * settings.ICE_MOTO_CO2_PER_KM) / 1000.0

    # 2. OPTION 2: Public Transport
    transit_fare_per_trip = transit_data["fare_vnd"] or settings.DEFAULT_PUBLIC_TRANSIT_FARE
    transit_total_cost = transit_fare_per_trip * monthly_trips
    transit_time_hours = (transit_data["duration_mins"] * monthly_trips) / 60.0
    transit_co2_kg = (monthly_km * settings.BUS_CO2_PER_PASSENGER_KM) / 1000.0

    # 3. OPTION 3: Electric Motorbike (EV)
    loan_cost = ev_loan_override if ev_loan_override is not None else settings.EV_DEFAULT_MONTHLY_LOAN
    kwh_needed = (monthly_km / 100.0) * settings.EV_MOTO_KWH_PER_100KM
    ev_elec_cost = kwh_needed * settings.ELECTRICITY_KWH_PRICE
    ev_total_cost = loan_cost + ev_elec_cost
    ev_time_hours = ice_time_hours  # Same driving routes
    ev_co2_kg = (monthly_km * settings.EV_MOTO_CO2_PER_KM) / 1000.0

    return [
        {
            "option_name": "Stay with Motorbike (ICE)",
            "monthly_cost_vnd": round(ice_total_cost),
            "one_way_duration_mins": round(driving_data["duration_mins"], 1),
            "monthly_time_spent_hours": round(ice_time_hours, 1),
            "monthly_co2_kg": round(ice_co2_kg, 2),
            "cost_breakdown": {
                "fuel_cost": round(ice_fuel_cost),
                "maintenance": round(ice_maint_cost),
                "insurance": round(ice_insurance)
            }
        },
        {
            "option_name": "Switch to Public Transport",
            "monthly_cost_vnd": round(transit_total_cost),
            "one_way_duration_mins": round(transit_data["duration_mins"], 1),
            "monthly_time_spent_hours": round(transit_time_hours, 1),
            "monthly_co2_kg": round(transit_co2_kg, 2),
            "cost_breakdown": {
                "fare_per_trip": transit_fare_per_trip,
                "total_fares": round(transit_total_cost)
            }
        },
        {
            "option_name": "Transfer to EV Motorbike",
            "monthly_cost_vnd": round(ev_total_cost),
            "one_way_duration_mins": round(driving_data["duration_mins"], 1),
            "monthly_time_spent_hours": round(ev_time_hours, 1),
            "monthly_co2_kg": round(ev_co2_kg, 2),
            "cost_breakdown": {
                "monthly_loan_or_depreciation": round(loan_cost),
                "electricity_cost": round(ev_elec_cost)
            }
        }
    ]