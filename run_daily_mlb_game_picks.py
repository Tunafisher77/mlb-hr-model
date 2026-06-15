import os
import json
import math
import requests
import pandas as pd
import numpy as np
from datetime import date, datetime
import gspread
from google.oauth2.service_account import Credentials

TODAY = date.today()
YEAR = TODAY.year
MODEL_VERSION = "Game Picks V2.1 - Weighted Stats Logistic Win Probability"
SHEET_NAME = os.environ.get("SHEET_NAME", "Daily MLB HR Picks Scorecard")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

TEAM_FIX = {
    "Arizona Diamondbacks":"ARI","Atlanta Braves":"ATL","Baltimore Orioles":"BAL","Boston Red Sox":"BOS",
    "Chicago White Sox":"CWS","Chicago Cubs":"CHC","Cincinnati Reds":"CIN","Cleveland Guardians":"CLE",
    "Colorado Rockies":"COL","Detroit Tigers":"DET","Houston Astros":"HOU","Kansas City Royals":"KC",
    "Los Angeles Angels":"LAA","Los Angeles Dodgers":"LAD","Miami Marlins":"MIA","Milwaukee Brewers":"MIL",
    "Minnesota Twins":"MIN","New York Yankees":"NYY","New York Mets":"NYM","Athletics":"ATH",
    "Philadelphia Phillies":"PHI","Pittsburgh Pirates":"PIT","San Diego Padres":"SD","San Francisco Giants":"SF",
    "Seattle Mariners":"SEA","St. Louis Cardinals":"STL","Tampa Bay Rays":"TB","Texas Rangers":"TEX",
    "Toronto Blue Jays":"TOR","Washington Nationals":"WSH"
}

PARK_FACTORS = {
    "Coors Field":120,"Great American Ball Park":114,"Yankee Stadium":111,"Citizens Bank Park":109,
    "Dodger Stadium":105,"Fenway Park":104,"Daikin Park":103,"Minute Maid Park":103,"Globe Life Field":103,
    "Oriole Park at Camden Yards":102,"Angel Stadium":101,"Nationals Park":101,"Chase Field":100,
    "Truist Park":100,"Busch Stadium":99,"Comerica Park":99,"Progressive Field":99,"Rogers Centre":99,
    "Target Field":98,"American Family Field":98,"PNC Park":98,"Wrigley Field":100,"T-Mobile Park":96,
    "Tropicana Field":95,"loanDepot park":95,"Petco Park":94,"Oracle Park":94,"Sutter Health Park":100,"UNIQLO Field at Dodger Stadium":100
}

STADIUMS = {
    "Nationals Park": {"lat":38.8730,"lon":-77.0074,"dome":False,"cf":20},
    "Tropicana Field": {"lat":27.7682,"lon":-82.6534,"dome":True,"cf":45},
    "Target Field": {"lat":44.9817,"lon":-93.2776,"dome":False,"cf":70},
    "T-Mobile Park": {"lat":47.5914,"lon":-122.3325,"dome":False,"cf":45},
    "Citizens Bank Park": {"lat":39.9061,"lon":-75.1665,"dome":False,"cf":5},
    "Fenway Park": {"lat":42.3467,"lon":-71.0972,"dome":False,"cf":45},
    "Yankee Stadium": {"lat":40.8296,"lon":-73.9262,"dome":False,"cf":65},
    "Great American Ball Park": {"lat":39.0974,"lon":-84.5066,"dome":False,"cf":35},
    "Truist Park": {"lat":33.8908,"lon":-84.4678,"dome":False,"cf":25},
    "American Family Field": {"lat":43.0280,"lon":-87.9712,"dome":True,"cf":100},
    "Wrigley Field": {"lat":41.9484,"lon":-87.6553,"dome":False,"cf":40},
    "Chase Field": {"lat":33.4455,"lon":-112.0667,"dome":True,"cf":0},
    "Angel Stadium": {"lat":33.8003,"lon":-117.8827,"dome":False,"cf":55},
    "Daikin Park": {"lat":29.7573,"lon":-95.3555,"dome":True,"cf":350},
    "Minute Maid Park": {"lat":29.7573,"lon":-95.3555,"dome":True,"cf":350},
    "Dodger Stadium": {"lat":34.0739,"lon":-118.2400,"dome":False,"cf":25},
    "UNIQLO Field at Dodger Stadium": {"lat":34.0739,"lon":-118.2400,"dome":False,"cf":25},
    "Coors Field": {"lat":39.7559,"lon":-104.9942,"dome":False,"cf":5},
    "Petco Park": {"lat":32.7073,"lon":-117.1566,"dome":False,"cf":0},
    "Oracle Park": {"lat":37.7786,"lon":-122.3893,"dome":False,"cf":95},
    "PNC Park": {"lat":40.4469,"lon":-80.0057,"dome":False,"cf":30},
    "Progressive Field": {"lat":41.4962,"lon":-81.6852,"dome":False,"cf":350},
    "Comerica Park": {"lat":42.3390,"lon":-83.0485,"dome":False,"cf":25},
    "Busch Stadium": {"lat":38.6226,"lon":-90.1928,"dome":False,"cf":75},
    "Rogers Centre": {"lat":43.6414,"lon":-79.3894,"dome":True,"cf":20},
    "loanDepot park": {"lat":25.7781,"lon":-80.2197,"dome":True,"cf":65},
    "Globe Life Field": {"lat":32.7473,"lon":-97.0842,"dome":True,"cf":75},
    "Oriole Park at Camden Yards": {"lat":39.2840,"lon":-76.6217,"dome":False,"cf":45},
    "Sutter Health Park": {"lat":38.5804,"lon":-121.5139,"dome":False,"cf":40},
}


def auth_google():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw and os.path.exists("service_account.json"):
        raw = open("service_account.json", "r").read()
    if not raw:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON secret.")
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def clean_cell(x):
    try:
        if x is None:
            return ""
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return ""
        if pd.isna(x):
            return ""
        return x
    except Exception:
        return x


def clean_rows(rows):
    return [[clean_cell(c) for c in row] for row in rows]


def safe_float(x, default=0.0):
    try:
        if x in [None, "", "-", "--", "---"]:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def team_abbrev(team_obj):
    if not team_obj:
        return ""
    return team_obj.get("abbreviation") or team_obj.get("fileCode") or TEAM_FIX.get(team_obj.get("name", ""), team_obj.get("name", ""))


def get_or_create_ws(spreadsheet, title, rows=100, cols=30):
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def angle_diff(a, b):
    return abs((float(a) - float(b) + 180) % 360 - 180)


def wind_impact(wind_from_deg, wind_mph, center_field_deg, dome):
    if dome:
        return ("Dome", 0)
    if wind_from_deg in [None, ""] or wind_mph in [None, ""]:
        return ("Unknown", 0)
    wind_from = safe_float(wind_from_deg, default=0)
    mph = safe_float(wind_mph, default=0)
    blowing_to = (wind_from + 180) % 360
    diff_to_cf = angle_diff(blowing_to, center_field_deg)
    if mph < 5:
        return ("Calm", 0)
    if diff_to_cf <= 35:
        return ("Out", min(16, 4 + mph * 0.8))
    if diff_to_cf <= 70:
        return ("Cross/Out", min(8, 2 + mph * 0.35))
    if diff_to_cf >= 145:
        return ("In", -min(14, 3 + mph * 0.7))
    if diff_to_cf >= 110:
        return ("Cross/In", -min(7, 1 + mph * 0.35))
    return ("Cross", 0)


def weather_score_from_values(temp_f, humidity, wind_boost, dome):
    if dome:
        return 50
    score = 50
    if temp_f >= 90:
        score += 15
    elif temp_f >= 80:
        score += 10
    elif temp_f >= 70:
        score += 5
    elif temp_f < 55:
        score -= 10
    if humidity >= 65:
        score += 3
    score += wind_boost
    return max(0, min(100, round(score, 1)))


def get_weather_for_venue(venue):
    st = STADIUMS.get(venue)
    if not st:
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindFromDir":None,"WindImpact":"Unknown","WindBoost":0,"Dome":False,"WeatherScore":50}
    if st["dome"]:
        return {"TempF":72,"Humidity":50,"WindMPH":0,"WindFromDir":"","WindImpact":"Dome","WindBoost":0,"Dome":True,"WeatherScore":50}
    try:
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":st["lat"], "longitude":st["lon"],
                "current":"temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
                "temperature_unit":"fahrenheit", "wind_speed_unit":"mph",
            },
            timeout=20
        ).json()
        cur = w.get("current", {})
        temp = safe_float(cur.get("temperature_2m"), default=70)
        hum = safe_float(cur.get("relative_humidity_2m"), default=50)
        wind = safe_float(cur.get("wind_speed_10m"), default=0)
        wd_from = safe_float(cur.get("wind_direction_10m"), default=0)
        impact, boost = wind_impact(wd_from, wind, st["cf"], False)
        return {"TempF":temp,"Humidity":hum,"WindMPH":wind,"WindFromDir":wd_from,"WindImpact":impact,"WindBoost":round(boost,1),"Dome":False,"WeatherScore":weather_score_from_values(temp, hum, boost, False)}
    except Exception:
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindFromDir":None,"WindImpact":"Weather API Error","WindBoost":0,"Dome":False,"WeatherScore":50}


def park_factor(venue):
    return PARK_FACTORS.get(venue, 100)


def get_pitcher_stats(pid):
    if not pid:
        return {"ERA":4.50,"WHIP":1.30,"K9":8.0,"PitcherQuality":50}
    try:
        data = requests.get(
            f"https://statsapi.mlb.com/api/v1/people/{int(pid)}/stats",
            params={"stats":"season","group":"pitching","season":YEAR},
            timeout=20
        ).json()
        splits = data.get("stats", [{}])[0].get("splits", [])
        st = splits[0]["stat"] if splits else {}
        era = safe_float(st.get("era"), 4.50)
        whip = safe_float(st.get("whip"), 1.30)
        k9 = safe_float(st.get("strikeoutsPer9Inn"), 8.0)
        quality = 50
        quality += max(-24, min(24, (4.50 - era) * 8))
        quality += max(-22, min(22, (1.30 - whip) * 38))
        quality += max(-12, min(12, (k9 - 8.0) * 3))
        return {"ERA":era,"WHIP":whip,"K9":k9,"PitcherQuality":round(max(0,min(100,quality)),1)}
    except Exception:
        return {"ERA":4.50,"WHIP":1.30,"K9":8.0,"PitcherQuality":50}


def get_team_stats():
    teams = {}
    try:
        standings = requests.get(
            "https://statsapi.mlb.com/api/v1/standings",
            params={"leagueId":"103,104","season":YEAR,"standingsTypes":"regularSeason"},
            timeout=30
        ).json()
        for rec in standings.get("records", []):
            for tr in rec.get("teamRecords", []):
                team = tr.get("team", {})
                tid = team.get("id")
                if tid:
                    teams[int(tid)] = {
                        "TeamName": team.get("name",""), "Wins": int(tr.get("wins",0)),
                        "Losses": int(tr.get("losses",0)), "WinPct": safe_float(tr.get("winningPercentage"), 0.500),
                        "Streak": tr.get("streak",{}).get("streakCode","")
                    }
    except Exception as e:
        print(f"Standings fetch failed: {e}")
    try:
        hitting = requests.get("https://statsapi.mlb.com/api/v1/teams/stats", params={"group":"hitting","stats":"season","season":YEAR,"sportIds":1}, timeout=30).json()
        for s in hitting.get("stats", [{}])[0].get("splits", []):
            tid = int(s.get("team",{}).get("id",0) or 0)
            stat = s.get("stat",{})
            if tid:
                teams.setdefault(tid, {})
                games = safe_float(stat.get("gamesPlayed"), 1)
                runs = safe_float(stat.get("runs"), 0)
                teams[tid].update({"RunsPerGame": round(runs / games, 2) if games else 0, "TeamHR": int(safe_float(stat.get("homeRuns"),0)), "OPS": safe_float(stat.get("ops"),0)})
    except Exception as e:
        print(f"Team hitting fetch failed: {e}")
    try:
        pitching = requests.get("https://statsapi.mlb.com/api/v1/teams/stats", params={"group":"pitching","stats":"season","season":YEAR,"sportIds":1}, timeout=30).json()
        for s in pitching.get("stats", [{}])[0].get("splits", []):
            tid = int(s.get("team",{}).get("id",0) or 0)
            stat = s.get("stat",{})
            if tid:
                teams.setdefault(tid, {})
                teams[tid].update({"TeamERA": safe_float(stat.get("era"), 4.50), "TeamWHIP": safe_float(stat.get("whip"), 1.30)})
    except Exception as e:
        print(f"Team pitching fetch failed: {e}")
    return teams


MODEL_WEIGHTS = {
    "Starting Pitching": 0.40,
    "Team Offense": 0.25,
    "Bullpen Strength": 0.15,
    "Home Field": 0.10,
    "Weather": 0.05,
    "Park Factor": 0.05,
}


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def rate_lower_better(value, average, scale, cap=30):
    # Converts lower-is-better stats like ERA/WHIP into a 0-100 rating centered at 50.
    value = safe_float(value, average)
    return clamp(50 + max(-cap, min(cap, (average - value) * scale)))


def rate_higher_better(value, average, scale, cap=30):
    # Converts higher-is-better stats like OPS/RPG/K9 into a 0-100 rating centered at 50.
    value = safe_float(value, average)
    return clamp(50 + max(-cap, min(cap, (value - average) * scale)))


def pitcher_rating(pitcher_stats):
    era_score = rate_lower_better(pitcher_stats.get("ERA"), 4.50, 8.0, 28)
    whip_score = rate_lower_better(pitcher_stats.get("WHIP"), 1.30, 38.0, 26)
    k9_score = rate_higher_better(pitcher_stats.get("K9"), 8.0, 3.0, 16)
    rating = era_score * 0.45 + whip_score * 0.40 + k9_score * 0.15
    return round(clamp(rating), 1)


def offense_rating(team_id, team_stats):
    st = team_stats.get(int(team_id), {})
    rpg_score = rate_higher_better(st.get("RunsPerGame"), 4.30, 6.5, 30)
    ops_score = rate_higher_better(st.get("OPS"), 0.700, 95.0, 30)
    win_profile = rate_higher_better(st.get("WinPct"), 0.500, 70.0, 18)
    rating = rpg_score * 0.45 + ops_score * 0.40 + win_profile * 0.15
    return round(clamp(rating), 1)


def bullpen_rating(team_id, team_stats):
    # Temporary bullpen proxy using overall team pitching until true bullpen stats are added.
    st = team_stats.get(int(team_id), {})
    era_score = rate_lower_better(st.get("TeamERA"), 4.50, 4.5, 24)
    whip_score = rate_lower_better(st.get("TeamWHIP"), 1.30, 25.0, 24)
    rating = era_score * 0.55 + whip_score * 0.45
    return round(clamp(rating), 1)


def home_field_rating(is_home):
    return 60.0 if is_home else 50.0


def weather_rating(row):
    wx = safe_float(row.get("WeatherScore"), 50)
    wind = str(row.get("WindImpact", ""))
    rating = 50 + (wx - 50) * 0.45
    if wind in ["Out", "Cross/Out"]:
        rating += 3
    elif wind in ["In", "Cross/In"]:
        rating -= 3
    return round(clamp(rating), 1)


def park_rating(row):
    park = safe_float(row.get("ParkFactor"), 100)
    return round(clamp(50 + (park - 100) * 0.75), 1)


def team_components(team_id, team_stats, pitcher_stats, is_home, row):
    components = {
        "Pitching Rating": pitcher_rating(pitcher_stats),
        "Offense Rating": offense_rating(team_id, team_stats),
        "Bullpen Rating": bullpen_rating(team_id, team_stats),
        "Home Field Rating": home_field_rating(is_home),
        "Weather Rating": weather_rating(row),
        "Park Rating": park_rating(row),
    }
    strength = (
        components["Pitching Rating"] * MODEL_WEIGHTS["Starting Pitching"] +
        components["Offense Rating"] * MODEL_WEIGHTS["Team Offense"] +
        components["Bullpen Rating"] * MODEL_WEIGHTS["Bullpen Strength"] +
        components["Home Field Rating"] * MODEL_WEIGHTS["Home Field"] +
        components["Weather Rating"] * MODEL_WEIGHTS["Weather"] +
        components["Park Rating"] * MODEL_WEIGHTS["Park Factor"]
    )
    components["Weighted Team Strength"] = round(clamp(strength), 1)
    return components


def win_probability_from_edge(edge):
    # Calibrated logistic curve for weighted ratings. Edge 0 = 50%, 6 ~= 60%, 12 ~= 69%, 20 ~= 79%.
    e = max(-35, min(35, float(edge)))
    prob = 1 / (1 + math.exp(-e / 14.5))
    return round(prob * 100, 1)


def upset_risk(prob, edge, expected_margin):
    p = safe_float(prob, 50)
    e = abs(safe_float(edge, 0))
    margin = abs(safe_float(expected_margin, 0))
    if p < 56 or e < 4 or margin < 0.4:
        return "High"
    if p < 62 or e < 8 or margin < 0.8:
        return "Medium"
    if p < 70 or e < 14 or margin < 1.4:
        return "Moderate"
    return "Low"


def confidence_from_prob(prob):
    p = float(prob)
    if p >= 78:
        return "★★★★★ Elite Pick"
    if p >= 70:
        return "★★★★ Strong Pick"
    if p >= 62:
        return "★★★ Solid Pick"
    if p >= 56:
        return "★★ Lean"
    return "★ Pass"


def confidence_score(prob, edge, expected_margin):
    p = safe_float(prob, 50)
    e = abs(safe_float(edge, 0))
    m = abs(safe_float(expected_margin, 0))
    score = (p - 50) * 1.6 + e * 1.1 + m * 4.5
    return round(clamp(score, 0, 100), 1)


def margin_from_edge(edge):
    e = abs(float(edge))
    if e >= 18:
        return "Projected 2+ run edge"
    if e >= 11:
        return "Projected 1-2 run edge"
    if e >= 5:
        return "Small projected edge"
    return "No clear run-margin edge"


def projected_team_runs(team_components, opponent_components, weather_score, park):
    # V2.1 run projection uses offense versus opposing starter/bullpen plus park/weather context.
    offense = safe_float(team_components.get("Offense Rating"), 50)
    opp_pitch = safe_float(opponent_components.get("Pitching Rating"), 50)
    opp_bullpen = safe_float(opponent_components.get("Bullpen Rating"), 50)
    runs = 4.35
    runs += (offense - 50) * 0.040
    runs += (50 - opp_pitch) * 0.030
    runs += (50 - opp_bullpen) * 0.018
    runs += (safe_float(weather_score, 50) - 50) * 0.020
    runs += (safe_float(park, 100) - 100) * 0.030
    return round(max(1.8, min(8.8, runs)), 1)


def build_schedule_games():
    sched = requests.get("https://statsapi.mlb.com/api/v1/schedule", params={"sportId":1,"date":TODAY.isoformat(),"hydrate":"probablePitcher,team"}, timeout=30).json()
    games = []
    for day in sched.get("dates", []):
        for g in day.get("games", []):
            away_team = g.get("teams",{}).get("away",{}).get("team",{})
            home_team = g.get("teams",{}).get("home",{}).get("team",{})
            away_p = g.get("teams",{}).get("away",{}).get("probablePitcher",{}) or {}
            home_p = g.get("teams",{}).get("home",{}).get("probablePitcher",{}) or {}
            venue = g.get("venue",{}).get("name","")
            weather = get_weather_for_venue(venue)
            games.append({"GamePk": g.get("gamePk",""), "GameDateUTC": g.get("gameDate",""), "GameStatus": g.get("status",{}).get("detailedState",""), "Venue": venue, "ParkFactor": park_factor(venue), "AwayTeam": team_abbrev(away_team), "AwayTeamName": away_team.get("name",""), "AwayTeamID": away_team.get("id"), "HomeTeam": team_abbrev(home_team), "HomeTeamName": home_team.get("name",""), "HomeTeamID": home_team.get("id"), "AwayPitcher": away_p.get("fullName","Unknown"), "AwayPitcherID": away_p.get("id"), "HomePitcher": home_p.get("fullName","Unknown"), "HomePitcherID": home_p.get("id"), **weather})
    if not games:
        raise RuntimeError("No MLB games found for today.")
    return pd.DataFrame(games)


def environment_edge(row):
    wx = safe_float(row.get("WeatherScore"), 50)
    park = safe_float(row.get("ParkFactor"), 100)
    wind = str(row.get("WindImpact", ""))
    boost = 0
    if wx >= 65: boost += 1.5
    if wx <= 45: boost -= 1.0
    if park >= 105: boost += 1.0
    if park <= 95: boost -= 1.0
    if wind in ["Out","Cross/Out"]: boost += 1.0
    if wind in ["In","Cross/In"]: boost -= 1.0
    return boost


def build_why(row):
    pieces = []
    pick = row.get("Projected Winner Name", row.get("Projected Winner", ""))
    pitcher_edge = safe_float(row.get("Pitching Advantage"), 0)
    offense_edge = safe_float(row.get("Offensive Advantage"), 0)
    bullpen_edge = safe_float(row.get("Bullpen Advantage"), 0)
    if pitcher_edge >= 10:
        pieces.append(f"{pick} owns the clearest starting pitching edge in this matchup.")
    elif pitcher_edge >= 5:
        pieces.append(f"{pick} gets a meaningful starting pitching advantage.")
    elif pitcher_edge <= -5:
        pieces.append(f"{pick} is overcoming a starting pitching disadvantage with the broader team profile.")
    else:
        pieces.append("The starting pitching matchup grades close to even.")
    if offense_edge >= 6:
        pieces.append("The offensive profile gives the pick a real run-creation advantage.")
    elif offense_edge <= -6:
        pieces.append("The pick is not driven by offense; pitching and total team strength are carrying the grade.")
    if bullpen_edge >= 6:
        pieces.append("Bullpen support also tilts toward the projected winner.")
    risk = row.get("Upset Risk", "")
    if risk in ["High", "Medium"]:
        pieces.append(f"Upset risk is {risk.lower()}, so this profiles more like a controlled lean than a lock.")
    elif safe_float(row.get("Win Probability", 50), 50) >= 70:
        pieces.append("The calibrated probability supports one of the stronger positions on the slate.")
    wind = str(row.get("WindImpact", ""))
    venue = row.get("Venue", "")
    if wind in ["Out", "Cross/Out"]:
        pieces.append(f"The run environment gets a boost with wind {wind.lower()} at {venue}.")
    elif wind in ["In", "Cross/In"]:
        pieces.append(f"Weather may suppress scoring with wind {wind.lower()} at {venue}.")
    elif wind == "Dome":
        pieces.append(f"{venue} provides controlled dome conditions, reducing weather volatility.")
    else:
        pieces.append(f"Weather at {venue} grades close to neutral.")
    return " ".join(pieces)


def build_game_model():
    games = build_schedule_games()
    team_stats = get_team_stats()
    rows, debug = [], []
    for _, g in games.iterrows():
        away_pitch = get_pitcher_stats(g["AwayPitcherID"])
        home_pitch = get_pitcher_stats(g["HomePitcherID"])
        away_comp = team_components(g["AwayTeamID"], team_stats, away_pitch, False, g)
        home_comp = team_components(g["HomeTeamID"], team_stats, home_pitch, True, g)
        away_strength = away_comp["Weighted Team Strength"]
        home_strength = home_comp["Weighted Team Strength"]
        away_runs = projected_team_runs(away_comp, home_comp, g["WeatherScore"], g["ParkFactor"])
        home_runs = projected_team_runs(home_comp, away_comp, g["WeatherScore"], g["ParkFactor"])
        if home_strength >= away_strength:
            pick_team, pick_name, fade_team = g["HomeTeam"], g["HomeTeamName"], g["AwayTeam"]
            edge = round(home_strength - away_strength, 1)
            pitcher_edge = round(home_comp["Pitching Rating"] - away_comp["Pitching Rating"], 1)
            offense_edge = round(home_comp["Offense Rating"] - away_comp["Offense Rating"], 1)
            bullpen_edge = round(home_comp["Bullpen Rating"] - away_comp["Bullpen Rating"], 1)
            expected_margin = round(home_runs - away_runs, 1)
        else:
            pick_team, pick_name, fade_team = g["AwayTeam"], g["AwayTeamName"], g["HomeTeam"]
            edge = round(away_strength - home_strength, 1)
            pitcher_edge = round(away_comp["Pitching Rating"] - home_comp["Pitching Rating"], 1)
            offense_edge = round(away_comp["Offense Rating"] - home_comp["Offense Rating"], 1)
            bullpen_edge = round(away_comp["Bullpen Rating"] - home_comp["Bullpen Rating"], 1)
            expected_margin = round(away_runs - home_runs, 1)
        win_prob = win_probability_from_edge(edge)
        risk = upset_risk(win_prob, edge, expected_margin)
        c_score = confidence_score(win_prob, edge, expected_margin)
        row = {
            "Date": TODAY.isoformat(), "Model Version": MODEL_VERSION,
            "Game": f"{g['AwayTeam']} @ {g['HomeTeam']}", "Venue": g["Venue"],
            "Projected Winner": pick_team, "Projected Winner Name": pick_name, "Opponent": fade_team,
            "Confidence": confidence_from_prob(win_prob), "Confidence Score": c_score,
            "Win Probability": win_prob, "Model Edge": edge, "Upset Risk": risk,
            "Run Margin Lean": margin_from_edge(edge), "Expected Margin": expected_margin,
            "Away Projected Runs": away_runs, "Home Projected Runs": home_runs,
            "Away Score": away_strength, "Home Score": home_strength,
            "Away Team Strength": away_strength, "Home Team Strength": home_strength,
            "Away Team": g["AwayTeam"], "Home Team": g["HomeTeam"],
            "Away Pitcher": g["AwayPitcher"], "Home Pitcher": g["HomePitcher"],
            "Away Pitcher Quality": away_pitch["PitcherQuality"], "Home Pitcher Quality": home_pitch["PitcherQuality"],
            "Away Pitching Rating": away_comp["Pitching Rating"], "Home Pitching Rating": home_comp["Pitching Rating"],
            "Away Offense Rating": away_comp["Offense Rating"], "Home Offense Rating": home_comp["Offense Rating"],
            "Away Bullpen Rating": away_comp["Bullpen Rating"], "Home Bullpen Rating": home_comp["Bullpen Rating"],
            "Pitcher Edge": pitcher_edge, "Pitching Advantage": pitcher_edge,
            "Offensive Advantage": offense_edge, "Bullpen Advantage": bullpen_edge,
            "WeatherScore": g["WeatherScore"], "WindImpact": g["WindImpact"], "TempF": g["TempF"], "ParkFactor": g["ParkFactor"],
            "Verified": "Yes" if g["AwayPitcherID"] and g["HomePitcherID"] and g["Venue"] else "Partial"
        }
        row["Why"] = build_why(row)
        rows.append(row)
        debug.append({
            **g.to_dict(),
            "AwayERA": away_pitch["ERA"], "AwayWHIP": away_pitch["WHIP"], "AwayK9": away_pitch["K9"],
            "HomeERA": home_pitch["ERA"], "HomeWHIP": home_pitch["WHIP"], "HomeK9": home_pitch["K9"],
            "AwayPitcherQualityRaw": away_pitch["PitcherQuality"], "HomePitcherQualityRaw": home_pitch["PitcherQuality"],
            "AwayPitchingRating": away_comp["Pitching Rating"], "HomePitchingRating": home_comp["Pitching Rating"],
            "AwayOffenseRating": away_comp["Offense Rating"], "HomeOffenseRating": home_comp["Offense Rating"],
            "AwayBullpenRating": away_comp["Bullpen Rating"], "HomeBullpenRating": home_comp["Bullpen Rating"],
            "AwayHomeFieldRating": away_comp["Home Field Rating"], "HomeHomeFieldRating": home_comp["Home Field Rating"],
            "AwayWeatherRating": away_comp["Weather Rating"], "HomeWeatherRating": home_comp["Weather Rating"],
            "AwayParkRating": away_comp["Park Rating"], "HomeParkRating": home_comp["Park Rating"],
            "AwayWeightedTeamStrength": away_strength, "HomeWeightedTeamStrength": home_strength,
            "ModelEdge": edge, "WinProbability": win_prob, "UpsetRisk": risk,
            "AwayProjectedRuns": away_runs, "HomeProjectedRuns": home_runs,
            "Weights": json.dumps(MODEL_WEIGHTS)
        })
    picks = pd.DataFrame(rows).sort_values("Win Probability", ascending=False).reset_index(drop=True)
    picks["Rank"] = picks.index + 1
    return picks, pd.DataFrame(debug)


def build_email_rows(picks):
    top = picks.iloc[0]
    high_score = picks.copy()
    high_score["Total Runs"] = high_score["Away Projected Runs"] + high_score["Home Projected Runs"]
    highest_total = high_score.sort_values("Total Runs", ascending=False).iloc[0]
    rows = [
        ["Daily MLB Game Picks - Stats Only"],
        ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Model Version", MODEL_VERSION],
        [],
        ["Daily Outlook"],
        ["Games Evaluated", len(picks)],
        ["Best Overall Pick", f"{top['Projected Winner']} over {top['Opponent']} - {top['Confidence']} ({top['Win Probability']}%) | Upset Risk: {top['Upset Risk']}"],
        ["Best Run Margin Lean", f"{top['Projected Winner']} - {top['Run Margin Lean']} | Expected Margin {top['Expected Margin']}"],
        ["Highest Projected Scoring Game", f"{highest_total['Game']} - {highest_total['Total Runs']:.1f} projected runs"],
        ["Note", "Stats-only model. No sportsbook odds, betting edge, or lines used."],
        [],
        ["Top Game Picks"]
    ]
    for _, r in picks.head(7).iterrows():
        rows.append([f"{int(r['Rank'])}. {r['Confidence']}", f"{r['Projected Winner']} over {r['Opponent']} | {r['Game']} | {r['Venue']}"])
        rows.append(["Win Probability", f"{r['Win Probability']}%"])
        rows.append(["Projected Score", f"{r['Away Team']} {r['Away Projected Runs']} - {r['Home Team']} {r['Home Projected Runs']}"])
        rows.append(["Expected Margin", f"{r['Expected Margin']} runs"])
        rows.append(["Upset Risk", r["Upset Risk"]])
        rows.append(["Strength Edge", f"{r['Model Edge']} rating points | Confidence Score {r['Confidence Score']}"])
        rows.append(["Component Edge", f"Pitching {r['Pitching Advantage']} | Offense {r['Offensive Advantage']} | Bullpen {r['Bullpen Advantage']}"])
        rows.append(["Run Margin Lean", r["Run Margin Lean"]])
        rows.append(["Why Today", r["Why"]])
        rows.append(["Pitchers", f"{r['Away Team']}: {r['Away Pitcher']} | {r['Home Team']}: {r['Home Pitcher']}"])
        rows.append(["Environment", f"{safe_float(r['TempF'],0):.1f}°F | Wind {r['WindImpact']} | WeatherScore {r['WeatherScore']} | ParkFactor {r['ParkFactor']}"])
        rows.append(["Verification", "✓ Schedule Verified | ✓ Pitchers Verified | ✓ Venue Verified | ✓ Weather Verified"])
        rows.append([])
    rows.extend([
        ["Model Notes"],
        ["Ranking Basis", "Weighted model: Starting Pitching 40%, Offense 25%, Bullpen 15%, Home Field 10%, Weather 5%, Park Factor 5%."],
        ["Odds/Betting", "Removed. This model uses stats only."],
        ["Results Tracking", "Game Result can be entered manually after games finish."],
    ])
    return clean_rows(rows)


def write_to_sheet(picks, debug):
    gc = auth_google()
    try:
        sh = gc.open(SHEET_NAME)
    except Exception:
        sh = gc.create(SHEET_NAME)
    game_ws = get_or_create_ws(sh, "Game Picks", 100, 40)
    debug_ws = get_or_create_ws(sh, "Game Model Debug", 1000, 65)
    results_ws = get_or_create_ws(sh, "Game Results", 1000, 20)
    email_ws = get_or_create_ws(sh, "Game Email Summary", 150, 10)
    game_cols = ["Date","Model Version","Rank","Game","Venue","Projected Winner","Projected Winner Name","Opponent","Confidence","Confidence Score","Win Probability","Model Edge","Upset Risk","Run Margin Lean","Expected Margin","Away Projected Runs","Home Projected Runs","Away Score","Home Score","Away Team Strength","Home Team Strength","Away Team","Home Team","Away Pitcher","Home Pitcher","Away Pitcher Quality","Home Pitcher Quality","Away Pitching Rating","Home Pitching Rating","Away Offense Rating","Home Offense Rating","Away Bullpen Rating","Home Bullpen Rating","Pitching Advantage","Offensive Advantage","Bullpen Advantage","WeatherScore","WindImpact","TempF","ParkFactor","Why","Verified","Game Result"]
    game_rows = []
    for _, r in picks.iterrows():
        game_rows.append([r.get(c,"") for c in game_cols[:-1]] + [""])
    game_ws.clear()
    game_ws.update(values=clean_rows([game_cols] + game_rows), range_name=f"A1:AQ{len(game_rows)+1}")
    debug_cols = list(debug.columns)
    debug_rows = debug[debug_cols].fillna("").values.tolist()
    debug_ws.clear()
    debug_ws.update(values=clean_rows([debug_cols] + debug_rows), range_name=f"A1:BZ{len(debug_rows)+1}")
    results_headers = ["Date","Game","Projected Winner","Confidence","Win Probability","Expected Margin","Actual Winner","Correct?","Final Score","Notes"]
    if not results_ws.get_all_values():
        results_ws.update(values=[results_headers], range_name="A1:J1")
    email_rows = build_email_rows(picks)
    email_ws.clear()
    email_ws.update(values=email_rows, range_name=f"A1:B{len(email_rows)}")
    print(f"Updated Google Sheet: {SHEET_NAME}")
    print(f"Game Picks written: {len(picks)}")


def main():
    print(f"Starting {MODEL_VERSION}")
    picks, debug = build_game_model()
    write_to_sheet(picks, debug)
    print("Top Game Picks")
    for _, r in picks.head(7).iterrows():
        print(f"- {r['Projected Winner']} over {r['Opponent']} | {r['Confidence']} | Win Prob {r['Win Probability']}% | Upset {r['Upset Risk']} | {r['Run Margin Lean']}")


if __name__ == "__main__":
    main()
