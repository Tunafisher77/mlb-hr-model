
import os, json, math, requests
import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
from pybaseball import statcast_batter
import gspread
from google.oauth2.service_account import Credentials

TODAY = date.today()
YEAR = TODAY.year
START = TODAY - timedelta(days=14)

MODEL_VERSION = "Automated V1 - V6.8B Logic"
SHEET_NAME = os.environ.get("SHEET_NAME", "Daily MLB HR Picks Scorecard")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def auth_google():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
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

def norm(s):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
    mn, mx = s.min(), s.max()
    if mx == mn:
        return pd.Series([50] * len(s), index=s.index)
    return ((s - mn) / (mx - mn) * 100).replace([np.inf, -np.inf], 0).fillna(0)

def safe_float(x):
    try:
        if x in [None, "", "-", "--", "---"]:
            return 0.0
        val = float(x)
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return val
    except Exception:
        return 0.0

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

def team_abbrev(team_obj):
    if not team_obj:
        return ""
    return team_obj.get("abbreviation") or team_obj.get("fileCode") or TEAM_FIX.get(team_obj.get("name", ""), team_obj.get("name", ""))

def tier_from_rank(rank):
    try:
        r = int(float(rank))
    except Exception:
        return ""
    if r <= 3:
        return "Primary"
    if r <= 6:
        return "Secondary"
    if r <= 9:
        return "Longshot"
    return ""

PARK_FACTORS = {
    "Coors Field":120,"Great American Ball Park":114,"Yankee Stadium":111,"Citizens Bank Park":109,
    "Dodger Stadium":105,"Fenway Park":104,"Daikin Park":103,"Minute Maid Park":103,"Globe Life Field":103,
    "Oriole Park at Camden Yards":102,"Angel Stadium":101,"Nationals Park":101,"Chase Field":100,
    "Truist Park":100,"Busch Stadium":99,"Comerica Park":99,"Progressive Field":99,"Rogers Centre":99,
    "Target Field":98,"American Family Field":98,"PNC Park":98,"Wrigley Field":100,"T-Mobile Park":96,
    "Tropicana Field":95,"loanDepot park":95,"Petco Park":94,"Oracle Park":94
}

def park_factor(venue):
    return PARK_FACTORS.get(venue, 100)

STADIUMS = {
    "Nationals Park":(38.8730,-77.0074,False),"Tropicana Field":(27.7682,-82.6534,True),
    "Target Field":(44.9817,-93.2776,False),"T-Mobile Park":(47.5914,-122.3325,False),
    "Citizens Bank Park":(39.9061,-75.1665,False),"Fenway Park":(42.3467,-71.0972,False),
    "Yankee Stadium":(40.8296,-73.9262,False),"Great American Ball Park":(39.0974,-84.5066,False),
    "Truist Park":(33.8908,-84.4678,False),"American Family Field":(43.0280,-87.9712,True),
    "Wrigley Field":(41.9484,-87.6553,False),"Chase Field":(33.4455,-112.0667,True),
    "Angel Stadium":(33.8003,-117.8827,False),"Daikin Park":(29.7573,-95.3555,True),
    "Minute Maid Park":(29.7573,-95.3555,True),"Dodger Stadium":(34.0739,-118.2400,False),
    "Coors Field":(39.7559,-104.9942,False),"Petco Park":(32.7073,-117.1566,False),
    "Oracle Park":(37.7786,-122.3893,False),"PNC Park":(40.4469,-80.0057,False),
    "Progressive Field":(41.4962,-81.6852,False),"Comerica Park":(42.3390,-83.0485,False),
    "Busch Stadium":(38.6226,-90.1928,False),"Rogers Centre":(43.6414,-79.3894,True),
    "loanDepot park":(25.7781,-80.2197,True),"Globe Life Field":(32.7473,-97.0842,True),
    "Oriole Park at Camden Yards":(39.2840,-76.6217,False)
}

def weather_score_from_values(temp_f, wind_mph, humidity, dome):
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
    if wind_mph >= 15:
        score += 12
    elif wind_mph >= 10:
        score += 8
    elif wind_mph >= 6:
        score += 4
    if humidity >= 65:
        score += 3
    return max(0, min(100, score))

def get_weather_for_venue(venue):
    if venue not in STADIUMS:
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindDir":"","Dome":False,"WeatherScore":50}
    lat, lon, dome = STADIUMS[venue]
    if dome:
        return {"TempF":72,"Humidity":50,"WindMPH":0,"WindDir":"","Dome":True,"WeatherScore":50}
    try:
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":lat,
                "longitude":lon,
                "current":"temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
                "temperature_unit":"fahrenheit",
                "wind_speed_unit":"mph",
            },
            timeout=20
        ).json()
        cur = w.get("current", {})
        temp = safe_float(cur.get("temperature_2m"))
        hum = safe_float(cur.get("relative_humidity_2m"))
        wind = safe_float(cur.get("wind_speed_10m"))
        wd = safe_float(cur.get("wind_direction_10m"))
        return {
            "TempF":temp,
            "Humidity":hum,
            "WindMPH":wind,
            "WindDir":wd,
            "Dome":False,
            "WeatherScore":weather_score_from_values(temp or 70, wind, hum or 50, False),
        }
    except Exception:
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindDir":"","Dome":False,"WeatherScore":50}

def get_or_create_ws(spreadsheet, title, rows=100, cols=30):
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

def build_model():
    u = "https://statsapi.mlb.com/api/v1/stats"
    p = {"stats":"season","group":"hitting","playerPool":"ALL","sortStat":"homeRuns","limit":30,"season":YEAR,"hydrate":"team"}
    d = requests.get(u, params=p, timeout=30).json()

    rows = []
    for s in d.get("stats", [{}])[0].get("splits", []):
        team = s.get("team", {})
        rows.append({
            "Player":s.get("player", {}).get("fullName"),
            "Player ID":s.get("player", {}).get("id"),
            "Team":team_abbrev(team),
            "Team Name":team.get("name", ""),
            "Season HR":int(s.get("stat", {}).get("homeRuns", 0) or 0),
        })
    model = pd.DataFrame(rows)

    out = []
    for _, r in model.iterrows():
        try:
            df = statcast_batter(START.strftime("%Y-%m-%d"), TODAY.strftime("%Y-%m-%d"), int(r["Player ID"]))
            b = df[df["launch_speed"].notna()]
            hh = ((b["launch_speed"] >= 95).mean() * 100) if len(b) else 0
            c100 = ((b["launch_speed"] >= 100).mean() * 100) if len(b) else 0
            fb = ((b["launch_angle"] > 10).mean() * 100) if len(b) else 0
            recent = ((df["events"] == "home_run").sum()) if len(df) else 0
            out.append([r["Player"], hh, c100, fb, recent])
        except Exception:
            out.append([r["Player"], 0, 0, 0, 0])

    stat = pd.DataFrame(out, columns=["Player","HardHit%","100+MPH%","FlyBall%","Last7HR"])
    model = model.merge(stat, on="Player", how="left")

    sched = requests.get(
        "https://statsapi.mlb.com/api/v1/schedule",
        params={"sportId":1,"date":TODAY.isoformat(),"hydrate":"probablePitcher,team"},
        timeout=30
    ).json()

    matchups = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            away_team = g["teams"]["away"]["team"]
            home_team = g["teams"]["home"]["team"]
            away = team_abbrev(away_team)
            home = team_abbrev(home_team)
            away_p = g["teams"]["away"].get("probablePitcher", {})
            home_p = g["teams"]["home"].get("probablePitcher", {})
            venue = g.get("venue", {}).get("name", "")
            weather = get_weather_for_venue(venue)
            base = {"Venue":venue, "ParkFactor":park_factor(venue), **weather}
            matchups.append({"Team":away,"Opponent":home,"Opposing Pitcher":home_p.get("fullName","Unknown"),"Opposing Pitcher ID":home_p.get("id"),**base})
            matchups.append({"Team":home,"Opponent":away,"Opposing Pitcher":away_p.get("fullName","Unknown"),"Opposing Pitcher ID":away_p.get("id"),**base})

    matchups = pd.DataFrame(matchups)

    pitch_rows = []
    for pid, pname in matchups[["Opposing Pitcher ID","Opposing Pitcher"]].drop_duplicates().dropna().values:
        try:
            data = requests.get(
                f"https://statsapi.mlb.com/api/v1/people/{int(pid)}/stats",
                params={"stats":"season","group":"pitching","season":YEAR},
                timeout=20
            ).json()
            splits = data.get("stats", [{}])[0].get("splits", [])
            st = splits[0]["stat"] if splits else {}
            pitch_rows.append({
                "Opposing Pitcher ID":pid,
                "Opposing Pitcher":pname,
                "ERA":safe_float(st.get("era")),
                "WHIP":safe_float(st.get("whip")),
                "K9":safe_float(st.get("strikeoutsPer9Inn")),
            })
        except Exception:
            pitch_rows.append({"Opposing Pitcher ID":pid,"Opposing Pitcher":pname,"ERA":0,"WHIP":0,"K9":0})

    pdf = pd.DataFrame(pitch_rows)
    pdf["PitcherVulnerability"] = norm(pdf["ERA"]) * 0.40 + norm(pdf["WHIP"]) * 0.30 + (100 - norm(pdf["K9"])) * 0.30

    model = model.merge(matchups, on="Team", how="left")
    model = model.merge(pdf[["Opposing Pitcher ID","ERA","WHIP","K9","PitcherVulnerability"]], on="Opposing Pitcher ID", how="left")

    fallback = pdf["PitcherVulnerability"].mean() if len(pdf) else 50
    model["PitcherVulnerability"] = model["PitcherVulnerability"].fillna(fallback)

    for c in ["ERA","WHIP","K9"]:
        model[c] = pd.to_numeric(model[c], errors="coerce").replace([np.inf,-np.inf],0).fillna(0)
    for c in ["ParkFactor","WeatherScore","TempF","Humidity","WindMPH"]:
        model[c] = pd.to_numeric(model[c], errors="coerce").replace([np.inf,-np.inf],50).fillna(50)

    model["Score"] = (
        norm(model["Season HR"]) * 0.07 +
        norm(model["Last7HR"]) * 0.13 +
        norm(model["HardHit%"]) * 0.17 +
        norm(model["100+MPH%"]) * 0.13 +
        norm(model["FlyBall%"]) * 0.09 +
        norm(model["PitcherVulnerability"]) * 0.20 +
        norm(model["ParkFactor"]) * 0.08 +
        norm(model["WeatherScore"]) * 0.13
    )

    model = model.replace([np.inf,-np.inf], 0).fillna("")
    model = model.sort_values("Score", ascending=False).reset_index(drop=True)
    model["Rank"] = model.index + 1
    model["Group"] = model["Rank"].apply(lambda x: "Group 1" if x <= 10 else ("Group 2" if x <= 20 else "Group 3"))
    model["Tier"] = model["Rank"].apply(tier_from_rank)
    return model, matchups

def write_to_sheet(model, matchups):
    gc = auth_google()
    try:
        sh = gc.open(SHEET_NAME)
    except Exception:
        sh = gc.create(SHEET_NAME)

    daily_ws = get_or_create_ws(sh, "Daily Picks", 500, 35)
    results_ws = get_or_create_ws(sh, "Model Results", 500, 35)
    weather_ws = get_or_create_ws(sh, "Weather Log", 500, 15)
    summary_ws = get_or_create_ws(sh, "Scorecard Summary", 100, 12)

    card = model[model["Rank"] <= 9].copy()

    daily_cols = ["Date","Model Version","Tier","Rank","Group","Player","Team","Opponent","Opposing Pitcher","Venue","Score","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","PitcherVulnerability","ParkFactor","TempF","WindMPH","WindDir","WeatherScore","HR Result"]
    daily_rows = []
    for _, r in card.iterrows():
        daily_rows.append([
            TODAY.isoformat(), MODEL_VERSION, r["Tier"], int(r["Rank"]), r["Group"], r["Player"], r["Team"], r["Opponent"], r["Opposing Pitcher"], r["Venue"],
            round(float(r["Score"]),2), int(r["Season HR"]), int(r["Last7HR"]), round(float(r["HardHit%"]),2), round(float(r["100+MPH%"]),2),
            round(float(r["FlyBall%"]),2), round(float(r["PitcherVulnerability"]),2), int(float(r["ParkFactor"])), round(float(r["TempF"]),1),
            round(float(r["WindMPH"]),1), r["WindDir"], round(float(r["WeatherScore"]),1), ""
        ])

    if not daily_ws.get_all_values():
        daily_ws.append_row(daily_cols)
    daily_ws.append_rows(clean_rows(daily_rows), value_input_option="USER_ENTERED")

    results_cols = ["Date","Model Version","Rank","Group","Player","Team","Opponent","Opposing Pitcher","ERA","WHIP","K9","PitcherVulnerability","Venue","ParkFactor","TempF","Humidity","WindMPH","WindDir","Dome","WeatherScore","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","Score"]
    results_rows = []
    for _, r in model.head(30).iterrows():
        results_rows.append([
            TODAY.isoformat(), MODEL_VERSION, int(r["Rank"]), r["Group"], r["Player"], r["Team"], r["Opponent"], r["Opposing Pitcher"],
            round(float(r["ERA"]),2), round(float(r["WHIP"]),2), round(float(r["K9"]),2), round(float(r["PitcherVulnerability"]),2), r["Venue"],
            int(float(r["ParkFactor"])), round(float(r["TempF"]),1), round(float(r["Humidity"]),1), round(float(r["WindMPH"]),1),
            r["WindDir"], str(r["Dome"]), round(float(r["WeatherScore"]),1), int(r["Season HR"]), int(r["Last7HR"]),
            round(float(r["HardHit%"]),2), round(float(r["100+MPH%"]),2), round(float(r["FlyBall%"]),2), round(float(r["Score"]),2)
        ])
    if not results_ws.get_all_values():
        results_ws.append_row(results_cols)
    results_ws.append_rows(clean_rows(results_rows), value_input_option="USER_ENTERED")

    weather_log = matchups[["Venue","TempF","Humidity","WindMPH","WindDir","Dome","WeatherScore"]].drop_duplicates().copy()
    weather_cols = ["Date","Venue","TempF","Humidity","WindMPH","WindDir","Dome","WeatherScore"]
    weather_rows = [[TODAY.isoformat(), r["Venue"], r["TempF"], r["Humidity"], r["WindMPH"], r["WindDir"], str(r["Dome"]), r["WeatherScore"]] for _, r in weather_log.iterrows()]
    if not weather_ws.get_all_values():
        weather_ws.append_row(weather_cols)
    weather_ws.append_rows(clean_rows(weather_rows), value_input_option="USER_ENTERED")

    summary_ws.clear()
    summary_rows = [
        ["Daily MLB HR Picks Scorecard",""],
        ["Last Automated Run",datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Model Version",MODEL_VERSION],
        ["Primary Picks",len(card[card["Tier"]=="Primary"])],
        ["Secondary Picks",len(card[card["Tier"]=="Secondary"])],
        ["Longshot Picks",len(card[card["Tier"]=="Longshot"])],
        ["Weather Status","Live Open-Meteo + manual stadium coordinates"],
        ["Sheet Updated","Yes"],
    ]
    summary_ws.update(values=clean_rows(summary_rows), range_name="A1:B8")

    print(f"Updated Google Sheet: {SHEET_NAME}")
    return card

def main():
    model, matchups = build_model()
    card = write_to_sheet(model, matchups)
    print("Daily HR Card")
    for tier in ["Primary","Secondary","Longshot"]:
        print("")
        print(tier)
        for _, r in card[card["Tier"] == tier].iterrows():
            print(f"- {r['Player']} ({r['Team']}) vs {r['Opposing Pitcher']} — Score {round(float(r['Score']),1)}")

if __name__ == "__main__":
    main()
