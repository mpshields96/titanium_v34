import streamlit as st
import pandas as pd
import requests
import json
import os
import time
from nba_api.stats.endpoints import leaguedashteamstats
from originator_engine import TitaniumOriginator

# --- PAGE CONFIG ---
st.set_page_config(page_title="TITANIUM V34 COMMAND", layout="wide", page_icon="⚡")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {width: 100%; background-color: #00FF00; color: black; font-weight: bold; border: none;}
    .metric-card {background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #00FF00;}
</style>
""", unsafe_allow_html=True)

# --- INITIALIZE ---
originator = TitaniumOriginator()

# --- LOAD V34 BRAIN ---
@st.cache_data
def load_v34_brain():
    try:
        if os.path.exists("titanium_v34.json"):
            with open("titanium_v34.json", "r") as f:
                return json.load(f)
        return None
    except: return None

v34_logic = load_v34_brain()

# --- LIVE DATA ENGINE (NBA API) ---
@st.cache_data(ttl=3600)
def fetch_nba_stats():
    """
    SECTION IV: Retrieves Live Efficiency Metrics.
    """
    try:
        # PULL LIVE DATA
        stats = leaguedashteamstats.LeagueDashTeamStats(season='2025-26').get_data_frames()[0]
        db = {}
        for _, row in stats.iterrows():
            name = row['TEAM_NAME'] # e.g., "L.A. Lakers"
            # TITANIUM SCORE = (NetRtg) * (Pace / 100)
            t_score = row['NET_RATING'] * (row['PACE'] / 100)
            
            db[name] = {
                "TitaniumScore": t_score,
                "NetRtg": row['NET_RATING'],
                "Pace": row['PACE'],
                "FT_Pct": row['FT_PCT'],
                "TOV_Pct": row['TM_TOV_PCT']
            }
        return db
    except: return {}

nba_db = fetch_nba_stats()

# --- THE MAPPING BRIDGE (CRITICAL FIX) ---
def get_titanium_stats(odds_api_name, stats_db):
    """
    Maps Odds API Names to NBA API Names.
    HARDCODED. NO GUESSING.
    """
    # MAP: "Odds API Name" -> "NBA API Name"
    mapping = {
        "Atlanta Hawks": "Atlanta Hawks",
        "Boston Celtics": "Boston Celtics",
        "Brooklyn Nets": "Brooklyn Nets",
        "Charlotte Hornets": "Charlotte Hornets",
        "Chicago Bulls": "Chicago Bulls",
        "Cleveland Cavaliers": "Cleveland Cavaliers",
        "Dallas Mavericks": "Dallas Mavericks",
        "Denver Nuggets": "Denver Nuggets",
        "Detroit Pistons": "Detroit Pistons",
        "Golden State Warriors": "Golden State Warriors",
        "Houston Rockets": "Houston Rockets",
        "Indiana Pacers": "Indiana Pacers",
        "Los Angeles Clippers": "L.A. Clippers", # CRITICAL FIX
        "LA Clippers": "L.A. Clippers",
        "Los Angeles Lakers": "L.A. Lakers",   # CRITICAL FIX
        "LA Lakers": "L.A. Lakers",
        "Memphis Grizzlies": "Memphis Grizzlies",
        "Miami Heat": "Miami Heat",
        "Milwaukee Bucks": "Milwaukee Bucks",
        "Minnesota Timberwolves": "Minnesota Timberwolves",
        "New Orleans Pelicans": "New Orleans Pelicans",
        "New York Knicks": "New York Knicks",
        "Oklahoma City Thunder": "Oklahoma City Thunder",
        "Orlando Magic": "Orlando Magic",
        "Philadelphia 76ers": "Philadelphia 76ers",
        "Phoenix Suns": "Phoenix Suns",
        "Portland Trail Blazers": "Portland Trail Blazers",
        "Sacramento Kings": "Sacramento Kings",
        "San Antonio Spurs": "San Antonio Spurs",
        "Toronto Raptors": "Toronto Raptors",
        "Utah Jazz": "Utah Jazz",
        "Washington Wizards": "Washington Wizards"
    }
    
    target_name = mapping.get(odds_api_name)
    if target_name and target_name in stats_db:
        return stats_db[target_name]
    return None

# --- MATHEMATICAL UTILS ---
def implied_prob(american_odds):
    if american_odds > 0: return 100 / (american_odds + 100)
    else: return abs(american_odds) / (abs(american_odds) + 100)

def calculate_kelly(odds, true_win_prob):
    # Quarter Kelly (0.25x)
    decimal = (100 / implied_prob(odds)) if odds > 0 else (1 + (100/abs(odds)))
    b = decimal - 1
    p = true_win_prob
    q = 1 - p
    if b == 0: return 0.0
    f_star = (b * p - q) / b
    kelly = f_star * 0.25
    if kelly < 0: return 0.0
    return min(kelly * 100, 2.0)

# --- V34 AUDIT CORE ---
def audit_game_v34(game, sport, logic, stats_db):
    approved_bets = []
    
    try:
        home = game['home_team']
        away = game['away_team']
        book = next((b for b in game['bookmakers'] if b['key'] in ['draftkings', 'fanduel', 'mgm']), game['bookmakers'][0])

        # 1. BANNED TEAM CHECKS
        banned = ["Milwaukee Bucks", "Pittsburgh Penguins"]
        if home in banned or away in banned: return []

        # 2. NBA SECTION IV (POWER SCORING)
        t_edge = None
        t_conf = 0.0
        
        if sport == "basketball_nba":
            h_stats = get_titanium_stats(home, stats_db)
            a_stats = get_titanium_stats(away, stats_db)
            
            # KILL SWITCH: NO STATS = NO BET
            if not h_stats or not a_stats:
                return [] 
                
            h_score = h_stats['TitaniumScore'] + 1.5 # Home Court
            a_score = a_stats['TitaniumScore']
            delta = h_score - a_score
            
            # THRESHOLD: Must be > 3.0 to pick a side
            if delta > 3.0: 
                t_edge = "HOME"
                t_conf = abs(delta)
            elif delta < -3.0: 
                t_edge = "AWAY"
                t_conf = abs(delta)
            else:
                return [] # NEUTRAL MATCHUP -> REJECT ENTIRE GAME

        # 3. MARKET AUDIT
        for market in book['markets']:
            # SPREADS ONLY FOR THIS TEST (To Ensure Directionality)
            if market['key'] == 'spreads':
                for outcome in market['outcomes']:
                    name = outcome['name']
                    price = outcome['price']
                    point = outcome['point']
                    
                    # ARTICLE 4: ODDS COLLAR
                    if price < -180 or price > 150: continue
                    
                    # SECTION XXXII: BLOWOUT SHIELD
                    status = "✅ V34 APPROVED"
                    if abs(point) > 10.5: status = "⚠️ BLOWOUT RISK"

                    # SECTION IV ENFORCEMENT
                    if sport == "basketball_nba":
                        if t_edge == "HOME" and name != home: continue
                        if t_edge == "AWAY" and name != away: continue
                        
                        # SECTION XXXIV: CLOSERS METRIC
                        # If Small Fav (-0.5 to -4.5), Check Fundamentals
                        if -4.5 <= point <= -0.5:
                            stats = h_stats if name == home else a_stats
                            if stats['FT_Pct'] < 0.71 or stats['TOV_Pct'] > 0.18:
                                continue # REJECT: Bad Closer

                    # KELLY
                    units = calculate_kelly(price, implied_prob(price) + (t_conf/100))
                    
                    if units > 0.05:
                        approved_bets.append({
                            "Matchup": f"{away} @ {home}",
                            "Target": name,
                            "Bet": f"Spread {point}",
                            "Odds": price,
                            "Kelly": f"{units:.2f}u",
                            "Status": status
                        })
                        
    except: return []
    return approved_bets

# --- UI ---
st.title("⚡ TITANIUM V34 COMMAND")
try:
    API_KEY = st.secrets["ODDS_API_KEY"]
except:
    API_KEY = st.sidebar.text_input("ENTER API KEY", type="password")

# SIDEBAR DIAGNOSTICS
st.sidebar.markdown("### SYSTEM STATUS")
if v34_logic: st.sidebar.success("BRAIN: ONLINE")
else: st.sidebar.error("BRAIN: OFFLINE")

if len(nba_db) > 25: st.sidebar.success(f"NBA API: {len(nba_db)} TEAMS LOADED")
else: st.sidebar.error(f"NBA API: {len(nba_db)} TEAMS (FAILURE)")

tab_scan, tab_math = st.tabs(["📡 V34 SCANNER", "🧬 ORIGINATOR"])

with tab_scan:
    if st.button("EXECUTE TITANIUM SEQUENCE"):
        if not API_KEY: st.error("KEY MISSING")
        else:
            with st.spinner("CALCULATING TITANIUM SCORES..."):
                data = fetch_odds("basketball_nba", API_KEY)
                if data:
                    ledger = []
                    for game in data:
                        bets = audit_game_v34(game, "basketball_nba", v34_logic, nba_db)
                        for b in bets: ledger.append(b)
                    
                    if ledger:
                        st.success(f"IDENTIFIED {len(ledger)} TARGETS")
                        st.dataframe(pd.DataFrame(ledger), use_container_width=True)
                    else:
                        st.warning("NO BETS SURVIVED V34 AUDIT.")
