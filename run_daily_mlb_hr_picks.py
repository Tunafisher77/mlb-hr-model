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

MODEL_VERSION = "Automated V11C - Consensus HR Odds Header Fix"
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


def normalize_name_for_odds(name):
    return "".join(ch.lower() for ch in str(name) if ch.isalnum())

def american_to_implied_pct(odds):
    try:
        odds = float(odds)
        if odds > 0:
            return round(10000 / (odds + 100), 2)
        if odds < 0:
            return round((-odds) / ((-odds) + 100) * 100, 2)
    except Exception:
        pass
    return ""


def sanitize_hr_odds(odds):
    """
    V9: Do not normalize suspicious odds.
    True 1+ HR props should usually be the Over 0.5 batter_home_runs market.
    If odds are extremely high, keep them out of BestHROdds and flag them.
    """
    try:
        o = float(odds)
    except Exception:
        return "", "Missing"
    if o > 5000:
        return "", "Suspicious odds ignored"
    return int(o), "OK"


def is_true_one_plus_hr_market(point):
    """
    Keep only Over 0.5 home run props.
    Exclude Over 1.5 / 2.5 alternate HR props that produce huge odds.
    """
    try:
        p = float(point)
        return abs(p - 0.5) < 0.01
    except Exception:
        # Some books may omit point for yes/no "to hit a HR"; allow blank only if needed.
        return False

def estimated_model_hr_prob(score):
    """
    Conservative first-pass conversion from model score to estimated HR probability.
    This is not calibrated yet. It gives us a starting value score until we collect results.
    """
    try:
        s = float(score)
        return round(max(1.0, min(22.0, 2.0 + (s / 100.0) * 18.0)), 2)
    except Exception:
        return ""

def odds_sanity_status(best_odds, avg_odds, books_found):
    """
    Basic anytime HR sanity checks.
    Normal 1+ HR props usually land roughly between +150 and +1500.
    Longshots can be higher, but anything very high should be reviewed.
    """
    try:
        b = float(best_odds)
        a = float(avg_odds)
    except Exception:
        return "No true 1+ HR odds found"
    if books_found < 2:
        return "Low book count"
    if b > 1800 or a > 1500:
        return "CHECK - unusually high HR odds"
    if b < 100 or a < 100:
        return "CHECK - unusually low HR odds"
    return "Consensus OK"

def fetch_hr_odds():
    """
    V11 odds engine:
    - Queries The Odds API batter_home_runs market
    - Keeps only Over 0.5 / true 1+ HR style outcomes
    - Collects all sportsbook prices per player
    - Removes obvious outliers
    - Returns best odds, average odds, number of books, and best book
    """
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        print("ODDS_API_KEY missing. Continuing without Vegas odds.")
        return {}, "Missing ODDS_API_KEY"

    sport = "baseball_mlb"
    base = "https://api.the-odds-api.com/v4"
    regions = os.environ.get("ODDS_REGIONS", "us")
    books = os.environ.get("ODDS_BOOKMAKERS", "")
    player_prices = {}
    status = "OK"

    try:
        events_resp = requests.get(
            f"{base}/sports/{sport}/events",
            params={"apiKey": api_key, "dateFormat": "iso"},
            timeout=30
        )
        if events_resp.status_code != 200:
            return {}, f"Events error {events_resp.status_code}: {events_resp.text[:200]}"
        events = events_resp.json()
    except Exception as e:
        return {}, f"Events exception: {e}"

    today_prefix = TODAY.isoformat()
    tomorrow_prefix = (TODAY + timedelta(days=1)).isoformat()
    todays_events = []
    for ev in events:
        ct = str(ev.get("commence_time", ""))
        if ct.startswith(today_prefix) or ct.startswith(tomorrow_prefix):
            todays_events.append(ev)

    for ev in todays_events:
        params = {
            "apiKey": api_key,
            "regions": regions,
            "markets": "batter_home_runs",
            "oddsFormat": "american"
        }
        if books.strip():
            params["bookmakers"] = books.strip()

        try:
            r = requests.get(
                f"{base}/sports/{sport}/events/{ev.get('id')}/odds",
                params=params,
                timeout=30
            )
            if r.status_code != 200:
                status = f"Some odds errors. Last {r.status_code}: {r.text[:120]}"
                continue
            data = r.json()
        except Exception as e:
            status = f"Some odds exceptions. Last: {e}"
            continue

        for bm in data.get("bookmakers", []):
            book_title = bm.get("title", bm.get("key", ""))
            for market in bm.get("markets", []):
                if market.get("key") != "batter_home_runs":
                    continue

                for out in market.get("outcomes", []):
                    outcome_name = str(out.get("name", ""))
                    player = out.get("description") or out.get("player") or ""
                    point = out.get("point", "")
                    price = out.get("price", "")

                    if not player or price in ["", None]:
                        continue

                    # Accept true 1+ HR market: Over 0.5.
                    # Reject alternate markets like Over 1.5 / 2.5.
                    if outcome_name.lower() not in ["over", "yes"] and "over" not in outcome_name.lower():
                        continue
                    if not is_true_one_plus_hr_market(point):
                        continue

                    try:
                        p = int(float(price))
                    except Exception:
                        continue

                    # Hard filter obvious bad alternate/parlay/boosted results.
                    if p > 2500 or p < 80:
                        continue

                    key = normalize_name_for_odds(player)
                    if not key:
                        continue

                    player_prices.setdefault(key, {
                        "PlayerOddsName": player,
                        "Prices": []
                    })
                    player_prices[key]["Prices"].append({
                        "book": book_title,
                        "price": p,
                        "point": point,
                    })

    odds_map = {}
    for key, item in player_prices.items():
        prices = item["Prices"]
        if not prices:
            continue

        # Remove outliers using simple median guard.
        values = sorted([x["price"] for x in prices])
        median = values[len(values)//2]
        filtered = []
        for x in prices:
            # Keep prices within a reasonable range around median.
            if x["price"] <= median + 600 and x["price"] >= max(80, median - 400):
                filtered.append(x)

        if not filtered:
            filtered = prices

        best = max(filtered, key=lambda x: x["price"])
        avg = round(sum(x["price"] for x in filtered) / len(filtered))
        books_found = len(filtered)

        odds_map[key] = {
            "PlayerOddsName": item["PlayerOddsName"],
            "BestHROdds": int(best["price"]),
            "AvgHROdds": int(avg),
            "BooksFound": books_found,
            "BestBook": best["book"],
            "OddsBook": best["book"],
            "OddsPoint": best["point"],
            "RawHROdds": int(best["price"]),
            "ImpliedProbPct": american_to_implied_pct(avg),
            "OddsNote": odds_sanity_status(best["price"], avg, books_found),
            "OddsStatus": status
        }

    return odds_map, status

def add_odds_to_model(model):
    odds_map, odds_status = fetch_hr_odds()
    rows = []
    for _, r in model.iterrows():
        key = normalize_name_for_odds(r.get("Player", ""))
        od = odds_map.get(key, {})

        best = od.get("BestHROdds", "")
        avg = od.get("AvgHROdds", "")
        implied = od.get("ImpliedProbPct", "")
        model_prob = estimated_model_hr_prob(r.get("Score", 0))

        if implied != "" and model_prob != "":
            edge = round(float(model_prob) - float(implied), 2)
        else:
            edge = ""

        value_score = float(r.get("Score", 0))
        if edge != "":
            value_score = value_score + max(0, edge) * 1.5

        rows.append({
            "Player": r.get("Player", ""),
            "PlayerOddsName": od.get("PlayerOddsName", ""),
            "BestHROdds": best,
            "AvgHROdds": avg,
            "BooksFound": od.get("BooksFound", ""),
            "BestBook": od.get("BestBook", ""),
            "RawHROdds": od.get("RawHROdds", ""),
            "OddsBook": od.get("OddsBook", ""),
            "OddsPoint": od.get("OddsPoint", ""),
            "OddsNote": od.get("OddsNote", "No true 1+ HR odds found"),
            "ImpliedProbPct": implied,
            "ModelProbEstPct": model_prob,
            "EdgePct": edge,
            "ValueScore": round(value_score, 2),
            "OddsStatus": od.get("OddsStatus", odds_status)
        })
    odds_df = pd.DataFrame(rows)
    model = model.merge(odds_df, on="Player", how="left")
    return model

def build_email_summary_rows(card):
    rows = []
    rows.append(["Daily MLB HR Picks Email Summary"])
    rows.append(["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    rows.append(["Model Version", MODEL_VERSION])
    rows.append([])
    rows.append(["Recommended Bets"])
    rec = card[card.get("ConfidenceGrade", "").isin(["A","B"])] if "ConfidenceGrade" in card.columns else pd.DataFrame()
    if rec.empty:
        rec = card.sort_values("ValueRank" if "ValueRank" in card.columns else "Rank").head(3)
    else:
        rec = rec.sort_values("ValueRank").head(5)
    for _, r in rec.iterrows():
        odds_txt = f" +{r.get('BestHROdds','')}" if str(r.get("BestHROdds","")).strip() else ""
        rows.append([
            r.get("ConfidenceGrade", ""),
            f"Value #{r.get('ValueRank','')} | {r['Player']} ({r['Team']}){odds_txt} — Score {round(float(r['Score']),1)} | Edge {r.get('EdgePct','')} | {r.get('WindImpact','')}"
        ])
    rows.append([])
    for tier in ["Primary", "Secondary", "Longshot"]:
        rows.append([tier])
        tier_df = card[card["Tier"] == tier].copy()
        for _, r in tier_df.iterrows():
            odds_txt = f" +{r.get('BestHROdds','')}" if str(r.get("BestHROdds","")).strip() else ""
            edge_txt = f" | Edge {r.get('EdgePct','')}" if str(r.get("EdgePct","")).strip() else ""
            weather_txt = f" | Weather {r.get('WeatherScore','')} ({r.get('WindImpact','')})"
            grade = r.get("ConfidenceGrade", "")
            value_rank = r.get("ValueRank", "")
            rows.append([
                int(r["Rank"]),
                f"{grade} | Value #{value_rank} | {r['Player']} ({r['Team']}) vs {r['Opposing Pitcher']}{odds_txt} — Score {round(float(r['Score']),1)}{edge_txt}{weather_txt}"
            ])
        rows.append([])
    rows.append(["Notes"])
    rows.append(["Use actual sportsbook odds in Daily Picks Odds column for ROI grading."])
    rows.append(["HR Result: 1 = HR, 0 = No HR."])
    return clean_rows(rows)

def refresh_email_summary(sh, card):
    ws = get_or_create_ws(sh, "Email Summary", 100, 10)
    rows = build_email_summary_rows(card)
    ws.clear()
    ws.update(values=rows, range_name=f"A1:B{len(rows)}")
    print("Email Summary updated")


def odds_bucket(odds):
    try:
        o = float(odds)
    except Exception:
        return "No Odds"
    if o < 300:
        return "< +300"
    if o < 600:
        return "+300 to +599"
    if o < 1000:
        return "+600 to +999"
    if o < 1500:
        return "+1000 to +1499"
    if o < 2500:
        return "+1500 to +2499"
    return "+2500+"

def refresh_recommended_bets(sh, card):
    """
    Creates a clean recommendation tab so Matt sees the best playable bets only.
    Keeps all 9 picks in Daily Picks, but this tab filters to stronger grades.
    """
    ws = get_or_create_ws(sh, "Recommended Bets", 100, 20)
    rec = card.copy()

    # Prefer A/B grades, but if there are fewer than 3, show top ValueRank picks.
    if "ConfidenceGrade" in rec.columns:
        filtered = rec[rec["ConfidenceGrade"].isin(["A", "B"])].copy()
    else:
        filtered = pd.DataFrame()

    if len(filtered) < 3:
        filtered = rec.sort_values("ValueRank" if "ValueRank" in rec.columns else "Rank").head(5).copy()
    else:
        filtered = filtered.sort_values("ValueRank").head(7).copy()

    headers = [
        "Date","Grade","ValueRank","Tier","Player","Team","Opponent","Opposing Pitcher",
        "Venue","Score","ValueScore","BestHROdds","AvgHROdds","BooksFound","BestBook","RawHROdds","OddsBook","EdgePct",
        "WeatherScore","WindImpact","PitcherConfidence","Recommendation"
    ]
    rows = [["Recommended Bets"], ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")], [], headers]

    for _, r in filtered.iterrows():
        grade = r.get("ConfidenceGrade", "")
        if grade == "A":
            note = "Strong play"
        elif grade == "B":
            note = "Playable"
        else:
            note = "Watchlist"
        rows.append([
            TODAY.isoformat(),
            grade,
            r.get("ValueRank",""),
            r.get("Tier",""),
            r.get("Player",""),
            r.get("Team",""),
            r.get("Opponent",""),
            r.get("Opposing Pitcher",""),
            r.get("Venue",""),
            round(float(r.get("Score",0)),2),
            r.get("ValueScore",""),
            r.get("BestHROdds",""),
            r.get("AvgHROdds",""),
            r.get("BooksFound",""),
            r.get("BestBook",""),
            r.get("RawHROdds",""),
            r.get("OddsBook",""),
            r.get("EdgePct",""),
            r.get("WeatherScore",""),
            r.get("WindImpact",""),
            r.get("PitcherConfidence",""),
            note
        ])

    ws.clear()
    ws.update(values=clean_rows(rows), range_name=f"A1:S{len(rows)}")
    print("Recommended Bets updated")


def ensure_header(ws, headers):
    """
    Makes sure row 1 has the full current header set.
    This fixes missing headers caused by older model versions that had fewer columns.
    It does not delete data.
    """
    existing = ws.row_values(1)
    if existing != headers:
        # AZ is wide enough for the current model columns.
        ws.update(values=[headers], range_name="A1:AZ1")

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
    daily_cols = ["Date","Model Version","Tier","Rank","Group","Player","Team","Opponent","Opposing Pitcher","PitcherSource","PitcherConfidence","Venue","Score","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","PitcherVulnerability","ParkFactor","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore","BestHROdds","AvgHROdds","BooksFound","BestBook","RawHROdds","OddsBook","OddsNote","ImpliedProbPct","ModelProbEstPct","EdgePct","ValueScore","ValueRank","ConfidenceGrade","OddsStatus","HR Result","Stake","Odds","ProfitLoss"]
    daily_rows = []
    for _, r in card.iterrows():
        daily_rows.append([TODAY.isoformat(),MODEL_VERSION,r["Tier"],int(r["Rank"]),r["Group"],r["Player"],r["Team"],r["Opponent"],r["Opposing Pitcher"],r.get("PitcherSource",""),r.get("PitcherConfidence",""),r["Venue"],round(float(r["Score"]),2),int(r["Season HR"]),int(r["Last7HR"]),round(float(r["HardHit%"]),2),round(float(r["100+MPH%"]),2),round(float(r["FlyBall%"]),2),round(float(r["PitcherVulnerability"]),2),int(float(r["ParkFactor"])),round(float(r["TempF"]),1),round(float(r["Humidity"]),1),round(float(r["WindMPH"]),1),r["WindFromDir"],r["WindBlowingTo"],r["WindAngleToCF"],r["WindImpact"],round(float(r["WindBoost"]),1),str(r["Dome"]),round(float(r["WeatherScore"]),1),r.get("BestHROdds",""),r.get("AvgHROdds",""),r.get("BooksFound",""),r.get("BestBook",""),r.get("RawHROdds",""),r.get("OddsBook",""),r.get("OddsNote",""),r.get("ImpliedProbPct",""),r.get("ModelProbEstPct",""),r.get("EdgePct",""),r.get("ValueScore",""),r.get("ValueRank",""),r.get("ConfidenceGrade",""),r.get("OddsStatus",""),"","","",""])

    ensure_header(daily_ws, daily_cols)
    daily_ws.append_rows(clean_rows(daily_rows), value_input_option="USER_ENTERED")

    results_cols = ["Date","Model Version","Rank","Group","Player","Team","Opponent","Opposing Pitcher","PitcherSource","PitcherConfidence","ERA","WHIP","K9","PitcherVulnerability","Venue","ParkFactor","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore","BestHROdds","AvgHROdds","BooksFound","BestBook","RawHROdds","OddsBook","OddsNote","ImpliedProbPct","ModelProbEstPct","EdgePct","ValueScore","ValueRank","ConfidenceGrade","OddsStatus","Season HR","Last7HR","HardHit%","100+MPH%","FlyBall%","Score"]
    results_rows = []
    for _, r in model.head(30).iterrows():
        results_rows.append([TODAY.isoformat(),MODEL_VERSION,int(r["Rank"]),r["Group"],r["Player"],r["Team"],r["Opponent"],r["Opposing Pitcher"],r.get("PitcherSource",""),r.get("PitcherConfidence",""),round(float(r["ERA"]),2),round(float(r["WHIP"]),2),round(float(r["K9"]),2),round(float(r["PitcherVulnerability"]),2),r["Venue"],int(float(r["ParkFactor"])),round(float(r["TempF"]),1),round(float(r["Humidity"]),1),round(float(r["WindMPH"]),1),r["WindFromDir"],r["WindBlowingTo"],r["WindAngleToCF"],r["WindImpact"],round(float(r["WindBoost"]),1),str(r["Dome"]),round(float(r["WeatherScore"]),1),r.get("BestHROdds",""),r.get("AvgHROdds",""),r.get("BooksFound",""),r.get("BestBook",""),r.get("RawHROdds",""),r.get("OddsBook",""),r.get("OddsNote",""),r.get("ImpliedProbPct",""),r.get("ModelProbEstPct",""),r.get("EdgePct",""),r.get("ValueScore",""),r.get("ValueRank",""),r.get("ConfidenceGrade",""),r.get("OddsStatus",""),int(r["Season HR"]),int(r["Last7HR"]),round(float(r["HardHit%"]),2),round(float(r["100+MPH%"]),2),round(float(r["FlyBall%"]),2),round(float(r["Score"]),2)])
    ensure_header(results_ws, results_cols)
    results_ws.append_rows(clean_rows(results_rows), value_input_option="USER_ENTERED")

    weather_cols = ["Date","Venue","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore"]
    weather_log = matchups[["Venue","TempF","Humidity","WindMPH","WindFromDir","WindBlowingTo","WindAngleToCF","WindImpact","WindBoost","Dome","WeatherScore"]].drop_duplicates().copy()
    weather_rows = [[TODAY.isoformat(), r["Venue"], r["TempF"], r["Humidity"], r["WindMPH"], r["WindFromDir"], r["WindBlowingTo"], r["WindAngleToCF"], r["WindImpact"], r["WindBoost"], str(r["Dome"]), r["WeatherScore"]] for _, r in weather_log.iterrows()]
    ensure_header(weather_ws, weather_cols)
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
        ["Vegas Odds","The Odds API batter_home_runs market; BestHROdds/OddsBook/EdgePct/ValueScore added"],
        ["ROI Tracking","ROI Dashboard tab added; headers auto-repaired; past-game auto-grading started"],
        ["Value Ranking","ValueRank and ConfidenceGrade added"],
        ["Recommended Bets","Recommended Bets tab added"],
        ["ROI Analytics","ROI Dashboard adds By Odds Range"],
        ["Email Summary","Email Summary tab upgraded for Matt/app script"],
        ["Sheet Updated","Yes"],
    ]
    summary_ws.update(values=clean_rows(summary_rows), range_name=f"A1:B{len(summary_rows)}")
    refresh_recommended_bets(sh, card)
    refresh_email_summary(sh, card)
    auto_grade_daily_picks(sh)
    refresh_roi_dashboard(sh)
    print(f"Updated Google Sheet: {SHEET_NAME}")
    return card


def confidence_grade(row):
    """
    Simple readable grade for betting confidence.
    A = strongest mix of value, model score, weather, and pitcher confidence.
    B = playable
    C = watchlist
    D = low confidence
    """
    try:
        score = float(row.get("Score", 0) or 0)
        value = float(row.get("ValueScore", score) or score)
        edge = float(row.get("EdgePct", 0) or 0)
        wx = float(row.get("WeatherScore", 50) or 50)
        pconf = str(row.get("PitcherConfidence", "")).lower()
    except Exception:
        return "C"

    grade_points = 0
    if value >= 85:
        grade_points += 2
    elif value >= 75:
        grade_points += 1

    if score >= 70:
        grade_points += 2
    elif score >= 62:
        grade_points += 1

    if edge >= 8:
        grade_points += 2
    elif edge >= 4:
        grade_points += 1

    if wx >= 70:
        grade_points += 1

    if pconf == "high":
        grade_points += 1
    elif pconf == "low":
        grade_points -= 1

    if grade_points >= 6:
        return "A"
    if grade_points >= 4:
        return "B"
    if grade_points >= 2:
        return "C"
    return "D"

def add_value_rank_and_grade(model):
    if "ValueScore" not in model.columns:
        model["ValueScore"] = model["Score"]
    model["ValueScoreNum"] = pd.to_numeric(
        model["ValueScore"], errors="coerce"
    ).fillna(pd.to_numeric(model["Score"], errors="coerce").fillna(0))
    model = model.sort_values("ValueScoreNum", ascending=False).reset_index(drop=True)
    model["ValueRank"] = model.index + 1
    model["ConfidenceGrade"] = model.apply(confidence_grade, axis=1)
    return model

def main():
    model, matchups = build_model()
    model = add_odds_to_model(model)
    model = add_value_rank_and_grade(model)
    # Value-aware rank after odds are added. If no odds are available, ValueScore equals Score.
    if 'ValueScore' in model.columns:
        model = model.sort_values('ValueScore', ascending=False).reset_index(drop=True)
        model['Rank'] = model.index + 1
        model['Group'] = model['Rank'].apply(lambda x: 'Group 1' if x <= 10 else ('Group 2' if x <= 20 else 'Group 3'))
        model['Tier'] = model['Rank'].apply(tier_from_rank)
    card = write_to_sheet(model, matchups)
    print("Daily HR Card")
    for tier in ["Primary","Secondary","Longshot"]:
        print("")
        print(tier)
        for _, r in card[card["Tier"] == tier].iterrows():
            print(f"- {r['Player']} ({r['Team']}) vs {r['Opposing Pitcher']} — Score {round(float(r['Score']),1)} — Odds {r.get('BestHROdds','')} {r.get('OddsBook','')} — Edge {r.get('EdgePct','')} — Weather {r.get('WeatherScore','')} ({r.get('WindImpact','')})")

if __name__ == "__main__":
    main()

