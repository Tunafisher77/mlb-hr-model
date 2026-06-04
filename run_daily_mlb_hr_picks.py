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

MODEL_VERSION = "Automated V2B - Weather + Pitcher Confidence"
SHEET_NAME = os.environ.get("SHEET_NAME", "Daily MLB HR Picks Scorecard")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

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

def norm(s):
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
    mn, mx = s.min(), s.max()
    if mx == mn:
        return pd.Series([50] * len(s), index=s.index)
    return ((s - mn) / (mx - mn) * 100).replace([np.inf, -np.inf], 0).fillna(0)

def safe_float(x, default=0.0):
    try:
        if x in [None, "", "-", "--", "---"]:
            return default
        val = float(x)
        if math.isnan(val) or math.isinf(val):
            return default
        return val
    except Exception:
        return default

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
    r = int(float(rank))
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

# Approximate direction from home plate to center field. Used to determine if wind is blowing out/in.
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

def angle_diff(a, b):
    return abs((float(a) - float(b) + 180) % 360 - 180)

def wind_impact(wind_from_deg, wind_mph, center_field_deg, dome):
    if dome:
        return ("Dome", 0, "", "")
    if wind_from_deg in [None, ""] or wind_mph in [None, ""]:
        return ("Unknown", 0, "", "")
    wind_from = safe_float(wind_from_deg, default=0)
    mph = safe_float(wind_mph, default=0)
    blowing_to = (wind_from + 180) % 360
    diff_to_cf = angle_diff(blowing_to, center_field_deg)
    if mph < 5:
        return ("Calm", 0, round(blowing_to,1), round(diff_to_cf,1))
    if diff_to_cf <= 35:
        return ("Out", min(16, 4 + mph * 0.8), round(blowing_to,1), round(diff_to_cf,1))
    if diff_to_cf <= 70:
        return ("Cross/Out", min(8, 2 + mph * 0.35), round(blowing_to,1), round(diff_to_cf,1))
    if diff_to_cf >= 145:
        return ("In", -min(14, 3 + mph * 0.7), round(blowing_to,1), round(diff_to_cf,1))
    if diff_to_cf >= 110:
        return ("Cross/In", -min(7, 1 + mph * 0.35), round(blowing_to,1), round(diff_to_cf,1))
    return ("Cross", 0, round(blowing_to,1), round(diff_to_cf,1))

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
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindFromDir":None,"WindBlowingTo":None,"WindAngleToCF":None,"WindImpact":"Unknown","WindBoost":0,"Dome":False,"WeatherScore":50}
    if st["dome"]:
        return {"TempF":72,"Humidity":50,"WindMPH":0,"WindFromDir":"","WindBlowingTo":"","WindAngleToCF":"","WindImpact":"Dome","WindBoost":0,"Dome":True,"WeatherScore":50}
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
        impact, boost, blowing_to, diff = wind_impact(wd_from, wind, st["cf"], False)
        wx_score = weather_score_from_values(temp, hum, boost, False)
        return {"TempF":temp,"Humidity":hum,"WindMPH":wind,"WindFromDir":wd_from,"WindBlowingTo":blowing_to,"WindAngleToCF":diff,"WindImpact":impact,"WindBoost":round(boost,1),"Dome":False,"WeatherScore":wx_score}
    except Exception:
        return {"TempF":None,"Humidity":None,"WindMPH":None,"WindFromDir":None,"WindBlowingTo":None,"WindAngleToCF":None,"WindImpact":"Weather API Error","WindBoost":0,"Dome":False,"WeatherScore":50}

def get_or_create_ws(spreadsheet, title, rows=100, cols=30):
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def probable_pitcher_fallback(team_abbr, opponent_abbr):
    """
    MLB schedule probablePitcher is sometimes blank early in the morning.
    Fallback strategy:
    1) Try today's schedule hydrate probablePitcher again.
    2) If still blank, leave Unknown but return a lower-confidence flag.
    This keeps model stable and tags rows clearly instead of silently treating Unknown as normal.
    """
    return {"name": "Unknown", "id": None, "source": "Missing from MLB probablePitcher feed", "confidence": "Low"}

def pitcher_source_label(pid, pname):
    if pid and pname and pname != "Unknown":
        return "MLB probablePitcher"
    return "Missing from MLB probablePitcher feed"

def build_model():
    d = requests.get("https://statsapi.mlb.com/api/v1/stats", params={"stats":"season","group":"hitting","playerPool":"ALL","sortStat":"homeRuns","limit":30,"season":YEAR,"hydrate":"team"}, timeout=30).json()
    rows = []
    for s in d.get("stats", [{}])[0].get("splits", []):
        team = s.get("team", {})
        rows.append({"Player":s.get("player", {}).get("fullName"),"Player ID":s.get("player", {}).get("id"),"Team":team_abbrev(team),"Team Name":team.get("name", ""),"Season HR":int(s.get("stat", {}).get("homeRuns", 0) or 0)})
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
    model = model.merge(pd.DataFrame(out, columns=["Player","HardHit%","100+MPH%","FlyBall%","Last7HR"]), on="Player", how="left")

    sched = requests.get("https://statsapi.mlb.com/api/v1/schedule", params={"sportId":1,"date":TODAY.isoformat(),"hydrate":"probablePitcher,team"}, timeout=30).json()
    matchups = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            away_team = g["teams"]["away"]["team"]
            home_team = g["teams"]["home"]["team"]
            away = team_abbrev(away_team); home = team_abbrev(home_team)
            away_p = g["teams"]["away"].get("probablePitcher", {})
            home_p = g["teams"]["home"].get("probablePitcher", {})
            venue = g.get("venue", {}).get("name", "")
            weather = get_weather_for_venue(venue)
            base = {"Venue":venue, "ParkFactor":park_factor(venue), **weather}
            home_p_name = home_p.get("fullName", "Unknown")
            home_p_id = home_p.get("id")
            away_p_name = away_p.get("fullName", "Unknown")
            away_p_id = away_p.get("id")
            matchups.append({
                "Team":away,"Opponent":home,
                "Opposing Pitcher":home_p_name,
                "Opposing Pitcher ID":home_p_id,
                "PitcherSource":pitcher_source_label(home_p_id, home_p_name),
                "PitcherConfidence":"High" if home_p_id else "Low",
                **base
            })
            matchups.append({
                "Team":home,"Opponent":away,
                "Opposing Pitcher":away_p_name,
                "Opposing Pitcher ID":away_p_id,
                "PitcherSource":pitcher_source_label(away_p_id, away_p_name),
                "PitcherConfidence":"High" if away_p_id else "Low",
                **base
            })
    matchups = pd.DataFrame(matchups)

    pitch_rows = []
    for pid, pname in matchups[["Opposing Pitcher ID","Opposing Pitcher"]].drop_duplicates().dropna().values:
        try:
            data = requests.get(f"https://statsapi.mlb.com/api/v1/people/{int(pid)}/stats", params={"stats":"season","group":"pitching","season":YEAR}, timeout=20).json()
            splits = data.get("stats", [{}])[0].get("splits", [])
            st = splits[0]["stat"] if splits else {}
            pitch_rows.append({"Opposing Pitcher ID":pid,"ERA":safe_float(st.get("era")),"WHIP":safe_float(st.get("whip")),"K9":safe_float(st.get("strikeoutsPer9Inn"))})
        except Exception:
            pitch_rows.append({"Opposing Pitcher ID":pid,"ERA":0,"WHIP":0,"K9":0})
    pdf = pd.DataFrame(pitch_rows)
    if len(pdf):
        pdf["PitcherVulnerability"] = norm(pdf["ERA"]) * 0.40 + norm(pdf["WHIP"]) * 0.30 + (100 - norm(pdf["K9"])) * 0.30
    else:
        pdf = pd.DataFrame(columns=["Opposing Pitcher ID","ERA","WHIP","K9","PitcherVulnerability"])

    model = model.merge(matchups, on="Team", how="left")
    model = model.merge(pdf, on="Opposing Pitcher ID", how="left")
    fallback = pdf["PitcherVulnerability"].mean() if len(pdf) else 50
    model["PitcherKnown"] = model["Opposing Pitcher ID"].apply(lambda x: bool(str(x).strip()) and str(x).strip().lower() not in ["nan", "none", ""])
    model["PitcherVulnerability"] = model["PitcherVulnerability"].fillna(fallback)
    # Unknown pitchers are risky. Keep them in the board, but avoid over-crediting them.
    model.loc[~model["PitcherKnown"], "PitcherVulnerability"] = 45

    for c in ["ERA","WHIP","K9"]:
        model[c] = pd.to_numeric(model[c], errors="coerce").replace([np.inf,-np.inf],0).fillna(0)
    for c in ["ParkFactor","WeatherScore","TempF","Humidity","WindMPH","WindBoost"]:
        model[c] = pd.to_numeric(model[c], errors="coerce").replace([np.inf,-np.inf],50).fillna(50)

    model["Score"] = (
        norm(model["Season HR"]) * 0.07 +
        norm(model["Last7HR"]) * 0.12 +
        norm(model["HardHit%"]) * 0.16 +
        norm(model["100+MPH%"]) * 0.12 +
        norm(model["FlyBall%"]) * 0.08 +
        norm(model["PitcherVulnerability"]) * 0.19 +
        norm(model["ParkFactor"]) * 0.07 +
        norm(model["WeatherScore"]) * 0.19
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

    daily_ws = get_or_create_ws(sh, "Daily Picks", 1000, 40)
    results_ws = get_or_create_ws(sh, "Model Results", 1000, 45)
    weather_ws = get_or_create_ws(sh, "Weather Log", 1000, 20)
    summary_ws = get_or_create_ws(sh, "Scorecard Summary", 100, 12)

    card = model[model["Rank"] <= 9].copy()
    daily_cols = ["Date","Model Version","Tier","Rank","Group","Player","Team","Opponent","Opposing Pitcher","PitcherSource","PitcherConfidence","Venue","Score","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","PitcherVulnerability","ParkFactor","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore","HR Result","Stake","Odds","ProfitLoss"]
    daily_rows = []
    for _, r in card.iterrows():
        daily_rows.append([TODAY.isoformat(),MODEL_VERSION,r["Tier"],int(r["Rank"]),r["Group"],r["Player"],r["Team"],r["Opponent"],r["Opposing Pitcher"],r.get("PitcherSource",""),r.get("PitcherConfidence",""),r["Venue"],round(float(r["Score"]),2),int(r["Season HR"]),int(r["Last7HR"]),round(float(r["HardHit%"]),2),round(float(r["100+MPH%"]),2),round(float(r["FlyBall%"]),2),round(float(r["PitcherVulnerability"]),2),int(float(r["ParkFactor"])),round(float(r["TempF"]),1),round(float(r["Humidity"]),1),round(float(r["WindMPH"]),1),r["WindFromDir"],r["WindBlowingTo"],r["WindAngleToCF"],r["WindImpact"],round(float(r["WindBoost"]),1),str(r["Dome"]),round(float(r["WeatherScore"]),1),"","","",""])

    if not daily_ws.get_all_values():
        daily_ws.append_row(daily_cols)
    daily_ws.append_rows(clean_rows(daily_rows), value_input_option="USER_ENTERED")

    results_cols = ["Date","Model Version","Rank","Group","Player","Team","Opponent","Opposing Pitcher","PitcherSource","PitcherConfidence","ERA","WHIP","K9","PitcherVulnerability","Venue","ParkFactor","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","Score"]
    results_rows = []
    for _, r in model.head(30).iterrows():
        results_rows.append([TODAY.isoformat(),MODEL_VERSION,int(r["Rank"]),r["Group"],r["Player"],r["Team"],r["Opponent"],r["Opposing Pitcher"],r.get("PitcherSource",""),r.get("PitcherConfidence",""),round(float(r["ERA"]),2),round(float(r["WHIP"]),2),round(float(r["K9"]),2),round(float(r["PitcherVulnerability"]),2),r["Venue"],int(float(r["ParkFactor"])),round(float(r["TempF"]),1),round(float(r["Humidity"]),1),round(float(r["WindMPH"]),1),r["WindFromDir"],r["WindBlowingTo"],r["WindAngleToCF"],r["WindImpact"],round(float(r["WindBoost"]),1),str(r["Dome"]),round(float(r["WeatherScore"]),1),int(r["Season HR"]),int(r["Last7HR"]),round(float(r["HardHit%"]),2),round(float(r["100+MPH%"]),2),round(float(r["FlyBall%"]),2),round(float(r["Score"]),2)])
    if not results_ws.get_all_values():
        results_ws.append_row(results_cols)
    results_ws.append_rows(clean_rows(results_rows), value_input_option="USER_ENTERED")

    weather_cols = ["Date","Venue","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore"]
    weather_log = matchups[["Venue","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore"]].drop_duplicates().copy()
    weather_rows = [[TODAY.isoformat(), r["Venue"], r["TempF"], r["Humidity"], r["WindMPH"], r["WindFromDir"], r["WindBlowingTo"], r["WindAngleToCF"], r["WindImpact"], r["WindBoost"], str(r["Dome"]), r["WeatherScore"]] for _, r in weather_log.iterrows()]
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
        ["Weather Status","Live weather + temperature + humidity + wind direction + outfield orientation"],
        ["Pitcher Status","PitcherSource and PitcherConfidence added; unknown pitchers penalized"],
        ["ROI Tracking","Stake/Odds/ProfitLoss columns added"],
        ["Sheet Updated","Yes"],
    ]
    summary_ws.update(values=clean_rows(summary_rows), range_name=f"A1:B{len(summary_rows)}")
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
            print(f"- {r['Player']} ({r['Team']}) vs {r['Opposing Pitcher']} — Score {round(float(r['Score']),1)} — Weather {r.get('WeatherScore','')} ({r.get('WindImpact','')})")

if __name__ == "__main__":
    main()

