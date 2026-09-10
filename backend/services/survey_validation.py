from __future__ import annotations

from typing import Any


SURVEY_CHOICES = {
    "age": {"less_18", "18_25", "26_35", "36_55", "56_75", "more_75"},
    "occup": {"state", "private", "fdi", "student", "retired"},
    "gender": {"male", "female", "prefer_not_to_say"},
    "purp": {"work", "education", "shopping", "leisure", "visit", "caring"},
    "vehic": {"moto", "car", "ebike", "bike", "walk", "bus", "taxi", "tram"},
    "freqpweek": {"1_3", "4_7", "8_10", "11_13", "14_16", "17_20", "more_20"},
    "reason": {"convinient", "timesaving", "cost", "other", "convinient timesaving", "convinient other", "cost convinient", "cost timesaving", "timesaving other", "cost other", "convinient timesaving other", "cost convinient timesaving", "cost convinient other", "cost timesaving other", "cost convinient timesaving other"},
    "own_car": {"0", "1", "2", "3", "4", "more_5"},
    "own_motob": {"0", "1", "2", "3", "4", "more_5"},
    "own_ebike": {"0", "1", "2", "3", "4", "more_5"},
    "own_bike": {"0", "1", "2", "3", "4", "more_5"},
    "freq_car": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "freq_motob": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "freq_ebike": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "freq_bike": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "freq_taxi": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "freq_bus": {"1_5", "6_10", "11_15", "16_20", "more_20"},
    "school_acc": {"very_bad", "bad", "neutral", "good", "very_good"},
    "market_acc": {"very_bad", "bad", "neutral", "good", "very_good"},
    "hosp_acc": {"very_bad", "bad", "neutral", "good", "very_good"},
    "bank_acc": {"very_bad", "bad", "neutral", "good", "very_good"},
    "leis_acc": {"very_bad", "bad", "neutral", "good", "very_good"},
    "type": {"high_rise", "old_building", "private_house", "private_new", "resettlement", "social_house"},
    "status": {"long_stay", "permanent", "short_stay"},
    "own": {"morgate", "owner", "parent_house", "rent"},
    "reas_not_car": {"cost", "jam", "parking", "slow", "unsafe"},
    "reas_not_motob": {"cost", "jam", "parking", "slow", "unsafe"},
    "reas_not_ebike": {"cost", "jam", "parking", "slow", "unsafe"},
    "reas_not_bike": {"cost", "jam", "parking", "slow", "unsafe"},
    "aware_ban": {"yes", "no", "donotcare"},
    "fut_veh": {"moto", "car", "ebike", "bike", "no"},
    "alt_car": {"0", "1"},
    "alt_ebike": {"0", "1"},
    "alt_bike": {"0", "1"},
    "alt_bus": {"0", "1"},
    "alt_ltrain": {"0", "1"},
    "alt_taxi": {"0", "1"},
    "alt_walk": {"0", "1"},
    "opinion_car": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_motob": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_ebike": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_bike": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_taxi": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_bus": {"verybad", "bad", "neutral", "good", "verygood"},
    "opinion_ban": {"strongdisagree", "disagree", "neutral", "agree", "strongagree"},
}

NUMERIC_RANGES = {
    "origlat": (8, 24),
    "origlon": (102, 110),
    "destlat": (8, 24),
    "destlon": (102, 110),
    "OD_dist": (0, 300),
    "travtime": (0, 1440),
    "dist_to_pub": (0, 10000),
}

REQUIRED_FIELDS = {"age", "occup", "gender", "origlat", "origlon", "destlat", "destlon", "purp", "vehic", "freqpweek"}
ALTERNATIVE_MODES = ("car", "ebike", "bike", "bus", "lighttrain", "taxi", "walk")


def validate_survey_payload(payload: dict[str, Any], allowed_fields: set[str]) -> tuple[dict[str, Any], dict[str, str]]:
    errors: dict[str, str] = {}
    cleaned = dict(payload)
    unknown = set(payload) - allowed_fields
    if unknown:
        errors["payload"] = f"Unknown fields: {', '.join(sorted(unknown))}"
    for field in REQUIRED_FIELDS:
        if payload.get(field) in (None, ""):
            errors[field] = "This field is required"
    for field, choices in SURVEY_CHOICES.items():
        value = payload.get(field)
        if value not in (None, "") and str(value) not in choices:
            errors[field] = "Select one of the available options"
    alternative_value = payload.get("alt_veh")
    if alternative_value not in (None, ""):
        tokens = str(alternative_value).split()
        if not tokens or len(tokens) != len(set(tokens)) or any(token not in ALTERNATIVE_MODES for token in tokens):
            errors["alt_veh"] = "Select one or more available alternative modes"
        else:
            cleaned["alt_veh"] = " ".join(mode for mode in ALTERNATIVE_MODES if mode in tokens)
    for field, (minimum, maximum) in NUMERIC_RANGES.items():
        value = payload.get(field)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors[field] = "Enter a valid number"
            continue
        if not minimum <= number <= maximum:
            errors[field] = f"Enter a value from {minimum} to {maximum}"
        else:
            cleaned[field] = number
    return cleaned, errors
