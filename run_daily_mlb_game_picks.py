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

MODEL_VERSION = "Game Picks V1 - Stats Only Moneyline + Run Margin"
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
    "Tropicana Field":95,"loanDepot park":95,"Petco Park":94,"Oracle Park":94
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
        return {"ERA":0,"WHIP":0,"K9":0,"PitcherQuality":50}
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
        quality = 50 + max(-20, min(20, (4.50 - era) * 7)) + max(-20, min(20, (1.30 - whip) * 35)) + max(-10, min(10, (k9 - 8.0) * 3))
        return {"ERA":era,"WHIP":whip,"K9":k9,"PitcherQuality":round(max(0,min(100,quality)),1)}
    except Exception:
        return {"ERA":0,"WHIP":0,"K9":0,"PitcherQuality":50}

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
                    teams[int(tid)] = {"TeamName": team.get("name",""), "Wins": int(tr.get("wins",0)), "Losses": int(tr.get("losses",0)), "WinPct": safe_float(tr.get("winningPercentage"), 0.500), "Streak": tr.get("streak",{}).get("streakCode","")}
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

def team_score(team_id, team_stats, pitcher_quality, is_home, env_boost):
    st = team_stats.get(int(team_id), {})
    win_pct = safe_float(st.get("WinPct"), 0.500)
    rpg = safe_float(st.get("RunsPerGame"), 4.3)
    ops = safe_float(st.get("OPS"), 0.700)
    team_era = safe_float(st.get("TeamERA"), 4.50)
    team_whip = safe_float(st.get("TeamWHIP"), 1.30)
    score = 50
    score += (win_pct - 0.500) * 70
    score += (rpg - 4.3) * 5
    score += (ops - 0.700) * 60
    score += (4.50 - team_era) * 3
    score += (1.30 - team_whip) * 10
    score += (pitcher_quality - 50) * 0.45
    if is_home:
        score += 3
    score += env_boost
    return round(max(0, min(100, score)), 1)

def confidence_from_edge(edge):
    e = abs(float(edge))
    if e >= 12:
        return "Strong Pick"
    if e >= 7:
        return "Solid Pick"
    if e >= 4:
        return "Lean"
    return "No Clear Edge"

def margin_from_edge(edge):
    e = float(edge)
    if abs(e) >= 12:
        return "Projected 2+ run lean"
    if abs(e) >= 7:
        return "Projected 1-2 run lean"
    if abs(e) >= 4:
        return "Small winner lean"
    return "No run margin lean"

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
    wind = str(row.get("WindImpact",""))
    boost = 0
    if wx >= 65:
        boost += 1
    if park >= 105:
        boost += 1
    if wind in ["Out","Cross/Out"]:
        boost += 1
    if wind in ["In","Cross/In"]:
        boost -= 1
    return boost

def build_game_model():
    games = build_schedule_games()
    team_stats = get_team_stats()
    rows, debug = [], []
    for _, g in games.iterrows():
        away_pitch = get_pitcher_stats(g["AwayPitcherID"])
        home_pitch = get_pitcher_stats(g["HomePitcherID"])
        env = environment_edge(g)
        away_score = team_score(g["AwayTeamID"], team_stats, away_pitch["PitcherQuality"], False, env)
        home_score = team_score(g["HomeTeamID"], team_stats, home_pitch["PitcherQuality"], True, env)
        if home_score >= away_score:
            pick_team, pick_name, fade_team = g["HomeTeam"], g["HomeTeamName"], g["AwayTeam"]
            edge = round(home_score - away_score, 1)
            pitcher_edge = round(home_pitch["PitcherQuality"] - away_pitch["PitcherQuality"], 1)
            pick_id = g["HomeTeamID"]
        else:
            pick_team, pick_name, fade_team = g["AwayTeam"], g["AwayTeamName"], g["HomeTeam"]
            edge = round(away_score - home_score, 1)
            pitcher_edge = round(away_pitch["PitcherQuality"] - home_pitch["PitcherQuality"], 1)
            pick_id = g["AwayTeamID"]
        why = []
        if pitcher_edge >= 8:
            why.append("clear starting pitcher edge")
        elif pitcher_edge >= 3:
            why.append("small starting pitcher edge")
        elif pitcher_edge <= -5:
            why.append("team strength offsets a pitching disadvantage")
        else:
            why.append("balanced starting pitcher matchup")
        st_pick = team_stats.get(int(pick_id), {})
        if safe_float(st_pick.get("WinPct"), 0.5) >= 0.560:
            why.append("strong season win profile")
        if safe_float(st_pick.get("RunsPerGame"), 4.3) >= 4.7:
            why.append("above-average run production")
        if str(g.get("WindImpact","")) in ["Out","Cross/Out"]:
            why.append("weather may support offense")
        if pick_team == g["HomeTeam"]:
            why.append("home-field advantage")
        rows.append({"Date": TODAY.isoformat(), "Model Version": MODEL_VERSION, "Game": f"{g['AwayTeam']} @ {g['HomeTeam']}", "Venue": g["Venue"], "Projected Winner": pick_team, "Projected Winner Name": pick_name, "Opponent": fade_team, "Confidence": confidence_from_edge(edge), "Model Edge": edge, "Run Margin Lean": margin_from_edge(edge), "Away Score": away_score, "Home Score": home_score, "Away Team": g["AwayTeam"], "Home Team": g["HomeTeam"], "Away Pitcher": g["AwayPitcher"], "Home Pitcher": g["HomePitcher"], "Away Pitcher Quality": away_pitch["PitcherQuality"], "Home Pitcher Quality": home_pitch["PitcherQuality"], "Pitcher Edge": pitcher_edge, "WeatherScore": g["WeatherScore"], "WindImpact": g["WindImpact"], "TempF": g["TempF"], "ParkFactor": g["ParkFactor"], "Why": "; ".join(why), "Verified": "Yes" if g["AwayPitcherID"] and g["HomePitcherID"] and g["Venue"] else "Partial"})
        debug.append({**g.to_dict(), "AwayERA": away_pitch["ERA"], "AwayWHIP": away_pitch["WHIP"], "AwayK9": away_pitch["K9"], "HomeERA": home_pitch["ERA"], "HomeWHIP": home_pitch["WHIP"], "HomeK9": home_pitch["K9"], "AwayPitcherQuality": away_pitch["PitcherQuality"], "HomePitcherQuality": home_pitch["PitcherQuality"], "AwayModelScore": away_score, "HomeModelScore": home_score})
    picks = pd.DataFrame(rows).sort_values("Model Edge", ascending=False).reset_index(drop=True)
    picks["Rank"] = picks.index + 1
    return picks, pd.DataFrame(debug)

def build_email_rows(picks):
    rows = [["Daily MLB Game Picks - Stats Only"], ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")], ["Model Version", MODEL_VERSION], [], ["Daily Outlook"], ["Games Evaluated", len(picks)], ["Top Projected Winner", f"{picks.iloc[0]['Projected Winner']} over {picks.iloc[0]['Opponent']} - {picks.iloc[0]['Confidence']}"], ["Best Run Margin Lean", f"{picks.iloc[0]['Projected Winner']} - {picks.iloc[0]['Run Margin Lean']}"], ["Note", "Stats-only model. No sportsbook odds, betting edge, or lines used."], [], ["Top Game Picks"]]
    for _, r in picks.head(7).iterrows():
        rows.append([f"{int(r['Rank'])}. {r['Confidence']}", f"{r['Projected Winner']} over {r['Opponent']} | {r['Game']} | {r['Venue']}"])
        rows.append(["Run Margin Lean", r["Run Margin Lean"]])
        rows.append(["Model Edge", r["Model Edge"]])
        rows.append(["Why", r["Why"]])
        rows.append(["Pitchers", f"{r['Away Team']}: {r['Away Pitcher']} | {r['Home Team']}: {r['Home Pitcher']}"])
        rows.append(["Environment", f"{r['TempF']}°F | Wind {r['WindImpact']} | WeatherScore {r['WeatherScore']} | ParkFactor {r['ParkFactor']}"])
        rows.append([])
    rows.extend([["Model Notes"], ["Ranking Basis", "Starting pitcher quality, team offense, team pitching profile, win profile, home field, park and weather."], ["Odds/Betting", "Removed. This model uses stats only."], ["Results Tracking", "Game Result can be entered manually after games finish."]])
    return clean_rows(rows)

def write_to_sheet(picks, debug):
    gc = auth_google()
    try:
        sh = gc.open(SHEET_NAME)
    except Exception:
        sh = gc.create(SHEET_NAME)
    game_ws = get_or_create_ws(sh, "Game Picks", 100, 35)
    debug_ws = get_or_create_ws(sh, "Game Model Debug", 1000, 60)
    results_ws = get_or_create_ws(sh, "Game Results", 1000, 20)
    email_ws = get_or_create_ws(sh, "Game Email Summary", 100, 10)
    game_cols = ["Date","Model Version","Rank","Game","Venue","Projected Winner","Projected Winner Name","Opponent","Confidence","Model Edge","Run Margin Lean","Away Score","Home Score","Away Team","Home Team","Away Pitcher","Home Pitcher","Away Pitcher Quality","Home Pitcher Quality","Pitcher Edge","WeatherScore","WindImpact","TempF","ParkFactor","Why","Verified","Game Result"]
    game_rows = []
    for _, r in picks.iterrows():
        game_rows.append([r.get(c,"") for c in game_cols[:-1]] + [""])
    game_ws.clear()
    game_ws.update(values=clean_rows([game_cols] + game_rows), range_name=f"A1:AA{len(game_rows)+1}")
    debug_cols = list(debug.columns)
    debug_rows = debug[debug_cols].fillna("").values.tolist()
    debug_ws.clear()
    debug_ws.update(values=clean_rows([debug_cols] + debug_rows), range_name=f"A1:AZ{len(debug_rows)+1}")
    results_headers = ["Date","Game","Projected Winner","Confidence","Run Margin Lean","Actual Winner","Correct?","Final Score","Notes"]
    if not results_ws.get_all_values():
        results_ws.update(values=[results_headers], range_name="A1:I1")
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
        print(f"- {r['Projected Winner']} over {r['Opponent']} | {r['Confidence']} | Edge {r['Model Edge']} | {r['Run Margin Lean']}")

if __name__ == "__main__":
    main()
