import streamlit as st
import pandas as pd
import requests
import json
import os
import time

# --- TITANIUM KEYVAULT ---
# USER PROVIDED KEY
ODDS_API_KEY = "01dc7be6ca076e6b79ac4f54001d142d"

# --- CONFIGURATION ---
st.set_page_config(page_title="TITANIUM V34.8 LIVE PROPS", layout="wide", page_icon="⚡")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {width: 100%; background-color: #00FF00; color: black; font-weight: bold; border: none;}
    .metric-card {background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #00FF00; margin-bottom: 10px;}
    .status-pass {color: #00FF00; font-weight: bold;}
    .status-fail {color: #FF4B4B; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

# --- V34 CONFIG LOADER ---
@st.cache_data
def load_v34_protocol():
    """Parses TITANIUM_V34_BLOAT_MASTER.json."""
    file_path = "titanium_v34.json"
    if not os.path.exists(file_path): return None
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            if "TITANIUM_V34_BLOAT_MASTER" in data:
                return data["TITANIUM_V34_BLOAT_MASTER"]
            return None
    except: return None

# --- ODDS API ENGINE (LIVE PROPS) ---
class OddsAPIEngine:
    def __init__(self, api_key):
        self.key = api_key
        self.base = "https://api.the-odds-api.com/v4/sports"
    
    def fetch_nba_events(self):
        """Get Game IDs."""
        url = f"{self.base}/basketball_nba/events?apiKey={self.key}&regions=us&markets=h2h"
        try:
            return requests.get(url).json()
        except: return []

    def fetch_player_props(self, event_id):
        """Get Props for a specific game."""
        # Markets: player_points (We focus on Points for KOTC)
        url = f"{self.base}/basketball_nba/events/{event_id}/odds?apiKey={self.key}&regions=us&markets=player_points&oddsFormat=american"
        try:
            r = requests.get(url)
            return r.json()
        except: return None

    def parse_props(self, data, h_team, a_team, stats_db):
        """Extracts Props & Applies V34 Logic."""
        targets = []
        bookmakers = data.get('bookmakers', [])
        if not bookmakers: return []

        # Prioritize DraftKings, fallback to first available
        dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
        
        # Get Defensive Stats
        h_stats = get_nba_team_stats(h_team, stats_db)
        a_stats = get_nba_team_stats(a_team, stats_db)
        
        # Defaults if stats missing
        if not h_stats: h_stats = {"DefRtg": 110, "Pace": 98}
        if not a_stats: a_stats = {"DefRtg": 110, "Pace": 98}

        for market in dk_book.get('markets', []):
            if market['key'] == 'player_points':
                for outcome in market['outcomes']:
                    # outcome: {'description': 'LeBron James', 'name': 'Over', 'price': -115, 'point': 24.5}
                    player_name = outcome['description']
                    side = outcome.get('name')
                    line = outcome.get('point')
                    price = outcome.get('price')
                    
                    if side == "Over":
                        # LOGIC: We don't know which team the player is on easily.
                        # V34 HEURISTIC: Check if EITHER defense is a "Green Light".
                        # If the Game has a DefRtg > 114 involved, we flag the stars.
                        
                        trigger = False
                        logic_msg = ""
                        
                        # Check threshold (Only look at stars > 18.5 pts)
                        if line > 18.5:
                            # Scenario A: Home Def is Bad (Target Away Player)
                            if h_stats['DefRtg'] >= 114.0:
                                trigger = True
                                logic_msg = f"Target vs {h_team} (DefRtg {h_stats['DefRtg']})"
                            
                            # Scenario B: Away Def is Bad (Target Home Player)
                            elif a_stats['DefRtg'] >= 114.0:
                                trigger = True
                                logic_msg = f"Target vs {a_team} (DefRtg {a_stats['DefRtg']})"
                                
                            # Scenario C: Pace is Extreme
                            elif h_stats['Pace'] > 100.0 or a_stats['Pace'] > 100.0:
                                trigger = True
                                logic_msg = "High Pace Environment"

                            if trigger:
                                targets.append({
                                    "Sport": "NBA",
                                    "Matchup": f"{h_team} vs {a_team}",
                                    "Bet_Type": "Player Prop",
                                    "Team_Target": player_name,
                                    "Line": f"Over {line}",
                                    "Price": str(price),
                                    "Sportsbook": dk_book['title'],
                                    "Logic": f"KOTC GREEN LIGHT: {logic_msg}"
                                })
        return targets

# --- NBA STATS ENGINE (FULL 30 TEAMS) ---
@st.cache_data(ttl=3600)
def fetch_nba_stats():
    """Retrieves NetRtg, Pace, DefRtg."""
    db = {}
    try:
        url = "http://www.espn.com/nba/hollinger/statistics"
        dfs = pd.read_html(url, header=1)
        df = dfs[0]
        df = df[df['TEAM'] != 'TEAM']
        for _, row in df.iterrows():
            try:
                name = row['TEAM']
                pace = float(row['PACE'])
                off = float(row['OFF'])
                deff = float(row['DEF'])
                db[name] = {"NetRtg": off - deff, "Pace": pace, "DefRtg": deff}
            except: continue
        if len(db) > 20: return db
    except: pass
    
    # STATIC BACKUP
    return {
        "Boston Celtics": {"NetRtg": 9.5, "Pace": 98.5, "DefRtg": 110.5}, "Oklahoma City Thunder": {"NetRtg": 8.2, "Pace": 101.0, "DefRtg": 111.0},
        "Denver Nuggets": {"NetRtg": 5.5, "Pace": 97.5, "DefRtg": 113.5}, "Minnesota Timberwolves": {"NetRtg": 6.1, "Pace": 98.0, "DefRtg": 109.0},
        "New York Knicks": {"NetRtg": 4.8, "Pace": 96.5, "DefRtg": 112.0}, "Milwaukee Bucks": {"NetRtg": -1.5, "Pace": 102.0, "DefRtg": 116.5},
        "Philadelphia 76ers": {"NetRtg": 3.2, "Pace": 99.0, "DefRtg": 113.0}, "Cleveland Cavaliers": {"NetRtg": 4.5, "Pace": 98.2, "DefRtg": 110.0},
        "Dallas Mavericks": {"NetRtg": -2.1, "Pace": 101.5, "DefRtg": 117.0}, "L.A. Clippers": {"NetRtg": 2.5, "Pace": 97.8, "DefRtg": 114.0},
        "L.A. Lakers": {"NetRtg": 1.2, "Pace": 100.5, "DefRtg": 115.0}, "Phoenix Suns": {"NetRtg": 3.8, "Pace": 99.5, "DefRtg": 114.5},
        "Sacramento Kings": {"NetRtg": 1.5, "Pace": 100.2, "DefRtg": 116.0}, "New Orleans Pelicans": {"NetRtg": 0.5, "Pace": 99.0, "DefRtg": 113.5},
        "Golden State Warriors": {"NetRtg": 1.8, "Pace": 100.0, "DefRtg": 114.2}, "Houston Rockets": {"NetRtg": 2.2, "Pace": 99.8, "DefRtg": 111.5},
        "Miami Heat": {"NetRtg": 0.8, "Pace": 97.0, "DefRtg": 112.5}, "Indiana Pacers": {"NetRtg": 1.5, "Pace": 103.5, "DefRtg": 119.0},
        "Orlando Magic": {"NetRtg": 2.1, "Pace": 98.5, "DefRtg": 110.0}, "Atlanta Hawks": {"NetRtg": -1.5, "Pace": 102.5, "DefRtg": 119.5},
        "Brooklyn Nets": {"NetRtg": -4.5, "Pace": 98.5, "DefRtg": 116.5}, "Toronto Raptors": {"NetRtg": -5.2, "Pace": 100.0, "DefRtg": 118.0},
        "Chicago Bulls": {"NetRtg": -3.8, "Pace": 99.2, "DefRtg": 115.5}, "Charlotte Hornets": {"NetRtg": -6.5, "Pace": 100.5, "DefRtg": 119.0},
        "Detroit Pistons": {"NetRtg": -7.2, "Pace": 101.0, "DefRtg": 118.5}, "Washington Wizards": {"NetRtg": -8.5, "Pace": 103.0, "DefRtg": 120.5},
        "Utah Jazz": {"NetRtg": -5.5, "Pace": 99.5, "DefRtg": 119.2}, "Portland Trail Blazers": {"NetRtg": -6.8, "Pace": 98.8, "DefRtg": 117.5},
        "San Antonio Spurs": {"NetRtg": -1.2, "Pace": 101.5, "DefRtg": 115.0}, "Memphis Grizzlies": {"NetRtg": 3.5, "Pace": 100.0, "DefRtg": 112.5}
    }

# --- MULTI-SPORT API (ESPN) ---
def get_live_data(sport):
    urls = {
        "NBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
        "NHL": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
        "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
    }
    url = urls.get(sport)
    if not url: return None
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return r.json() if r.status_code == 200 else None
    except: return None

# --- HELPER: TEAM MAPPING ---
def get_nba_team_stats(name, db):
    mapping = {"LA Clippers": "L.A. Clippers", "Los Angeles Clippers": "L.A. Clippers", "LA Lakers": "L.A. Lakers", "Los Angeles Lakers": "L.A. Lakers"}
    target = mapping.get(name, name)
    if target in db: return db[target]
    mascot = name.split()[-1]
    for k in db:
        if mascot in k: return db[k]
    return None

def _parse_odds(odds_obj, home_comp, away_comp):
    h_ml = odds_obj.get('homeTeamOdds', {}).get('moneyLine')
    a_ml = odds_obj.get('awayTeamOdds', {}).get('moneyLine')
    if not h_ml: h_ml = home_comp.get('lines', [{}])[0].get('moneyLine')
    if not a_ml: a_ml = away_comp.get('lines', [{}])[0].get('moneyLine')
    try: h_ml = float(h_ml) if h_ml else None
    except: h_ml = None
    try: a_ml = float(a_ml) if a_ml else None
    except: a_ml = None
    spread_str = odds_obj.get('details', '0')
    return h_ml, a_ml, spread_str

# --- GATEKEEPER LOGIC ---
class TitaniumGatekeeper:
    def __init__(self, config, stats_db):
        self.config = config
        self.stats_db = stats_db
        self.bans = ["Milwaukee Bucks", "Pittsburgh Penguins"]

    def _get_provider(self, odds_obj):
        try: return odds_obj.get('provider', {}).get('name', 'Consensus')
        except: return "Consensus"

    def audit_game(self, event, sport):
        if sport == "NBA": return self.audit_nba(event)
        elif sport == "NHL": return self.audit_nhl(event)
        elif sport == "NCAAB": return self.audit_ncaab(event)
        return []

    # --- NBA LOGIC ---
    def audit_nba(self, event):
        approved = []
        try:
            short_name = event['shortName']
            comp = event['competitions'][0]
            home = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            away = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            h_name, a_name = home['team']['displayName'], away['team']['displayName']

            if any(b in h_name for b in self.bans) or any(b in a_name for b in self.bans): return []

            # STATS
            h_st, a_st = get_nba_team_stats(h_name, self.stats_db), get_nba_team_stats(a_name, self.stats_db)
            t_edge = None
            t_edge_val = 0.0
            if h_st and a_st:
                h_sc = (h_st['NetRtg'] * (h_st['Pace']/100)) + 1.5
                a_sc = (a_st['NetRtg'] * (a_st['Pace']/100))
                delta = h_sc - a_sc
                if delta > 3.0: 
                    t_edge = "HOME"
                    t_edge_val = abs(delta)
                elif delta < -3.0: 
                    t_edge = "AWAY"
                    t_edge_val = abs(delta)
            
            if comp.get('odds'):
                odds_obj = comp['odds'][0]
                provider = self._get_provider(odds_obj)
                h_ml, a_ml, spread_str = _parse_odds(odds_obj, home, away)
                
                # SPREAD
                if t_edge:
                    try:
                        parts = spread_str.split(" ")
                        fav_abbr, spread_val = parts[0], float(parts[1])
                        is_home_fav = (home['team']['abbreviation'] == fav_abbr)
                        target_side = "HOME" if t_edge == "HOME" else "AWAY"
                        target_team = h_name if target_side == "HOME" else a_name
                        final_line = spread_val
                        if not ((target_side == "HOME" and is_home_fav) or (target_side == "AWAY" and not is_home_fav)):
                            final_line = spread_val * -1
                        if t_edge == target_side and abs(final_line) <= 10.5:
                            price = str(odds_obj.get('price', -110))
                            approved.append({
                                "Sport": "NBA", "Matchup": short_name, "Bet_Type": "Spread",
                                "Team_Target": target_team, "Line": str(final_line), "Price": price, 
                                "Sportsbook": provider, "Logic": f"Titanium Edge {t_edge_val:.1f} | Blowout Check Passed"
                            })
                    except: pass
                
                # MONEYLINE
                if h_ml and t_edge == "HOME" and -200 <= h_ml <= 150:
                     approved.append({"Sport": "NBA", "Matchup": short_name, "Bet_Type": "Moneyline", "Team_Target": h_name, "Line": "ML", "Price": str(h_ml), "Sportsbook": provider, "Logic": f"Titanium Edge {t_edge_val:.1f} | ML Value"})
                if a_ml and t_edge == "AWAY" and -200 <= a_ml <= 150:
                     approved.append({"Sport": "NBA", "Matchup": short_name, "Bet_Type": "Moneyline", "Team_Target": a_name, "Line": "ML", "Price": str(a_ml), "Sportsbook": provider, "Logic": f"Titanium Edge {t_edge_val:.1f} | ML Value"})

        except: pass
        return approved

    # --- NHL LOGIC ---
    def audit_nhl(self, event):
        approved = []
        try:
            short_name = event['shortName']
            comp = event['competitions'][0]
            home = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
            away = next(c for c in comp['competitors'] if c['homeAway'] == 'away')
            h_name, a_name = home['team']['displayName'], away['team']['displayName']

            if "Penguins" in h_name or "Penguins" in a_name: return []

            if not comp.get('odds'): return []
            odds_obj = comp['odds'][0]
            provider = self._get_provider(odds_obj)
            h_ml, a_ml, spread_str = _parse_odds(odds_obj, home, away)
            
            spread_val = 1.5
            try: spread_val = float(spread_str.split(" ")[1])
            except: pass

            if h_ml:
                if h_ml < -200:
                     approved.append({"Sport": "NHL", "Matchup": short_name, "Bet_Type": "Puck Line", "Team_Target": h_name, "Line": f"-{spread_val}", "Price": str(odds_obj.get('price', -110)), "Sportsbook": provider, "Logic": "Safety Valve (ML < -200)"})
                elif -200 <= h_ml <= 150:
                     approved.append({"Sport": "NHL", "Matchup": short_name, "Bet_Type": "Moneyline", "Team_Target": h_name, "Line": "ML", "Price": str(h_ml), "Sportsbook": provider, "Logic": "Odds Collar Pass"})
            if a_ml:
                if a_ml < -200:
                     approved.append({"Sport": "NHL", "Matchup": short_name, "Bet_Type": "Puck Line", "Team_Target": a_name, "Line": f"-{spread_val}", "Price": str(odds_obj.get('price', -110)), "Sportsbook": provider, "Logic": "Safety Valve (ML < -200)"})
                elif -200 <= a_ml <= 150:
                     approved.append({"Sport": "NHL", "Matchup": short_name, "Bet_Type": "Moneyline", "Team_Target": a_name, "Line": "ML", "Price": str(a_ml), "Sportsbook": provider, "Logic": "Odds Collar Pass"})
        except: pass
        return approved

    # --- NCAAB LOGIC ---
    def audit_ncaab(self, event):
        approved = []
        try:
            short_name = event['shortName']
            comp = event['competitions'][0]
            if not comp.get('odds'): return []
            odds_obj = comp['odds'][0]
            provider = self._get_provider(odds_obj)
            try:
                spread_str = odds_obj.get('details', '0')
                parts = spread_str.split(" ")
                spread_val = float(parts[1])
                team_abbr = parts[0]
                home = next(c for c in comp['competitors'] if c['homeAway'] == 'home')
                target_name = home['team']['displayName'] if home['team']['abbreviation'] == team_abbr else next(c for c in comp['competitors'] if c['homeAway'] == 'away')['team']['displayName']
                logic_note = "V34 Approved"
                if -4.5 <= spread_val <= -0.5:
                    logic_note = "⚠️ CLOSERS METRIC: Audit FT% > 71%"
                price = float(odds_obj.get('price', -110))
                if -180 <= price <= 150:
                    approved.append({
                        "Sport": "NCAAB", "Matchup": short_name, "Bet_Type": "Spread",
                        "Team_Target": target_name, "Line": str(spread_val),
                        "Price": str(price), "Sportsbook": provider, "Logic": logic_note
                    })
            except: pass
        except: pass
        return approved

# --- MAIN UI ---
def main():
    st.sidebar.title("TITANIUM V34.8 LIVE PROPS")
    sport = st.sidebar.selectbox("PROTOCOL SELECTION", ["NBA", "NHL", "NCAAB", "NFL (Offseason)"])
    
    config = load_v34_protocol()
    if config: st.sidebar.success("BRAIN: ONLINE")
    else: st.sidebar.error("BRAIN: OFFLINE")
    
    st.title(f"⚡ TITANIUM V34.8 | {sport}")
    
    # --- NBA EXECUTION ---
    if sport == "NBA":
        if st.button("EXECUTE TITANIUM SEQUENCE"):
            with st.spinner("AUDITING MARKETS (Connecting to Odds API & ESPN)..."):
                
                # 1. FETCH LIVE PROPS
                odds_engine = OddsAPIEngine(ODDS_API_KEY)
                stats_db = fetch_nba_stats()
                
                # Fetch Events first
                events = odds_engine.fetch_nba_events() # Cost: 1
                prop_ledger = []
                
                if events:
                    for event in events:
                        # Fetch Props for this game
                        game_props = odds_engine.fetch_player_props(event['id']) # Cost: 1 per game
                        if game_props:
                            # Parse
                            p_targets = odds_engine.parse_props(game_props, event['home_team'], event['away_team'], stats_db)
                            prop_ledger.extend(p_targets)
                
                # 2. FETCH SPREADS/ML (ESPN)
                gatekeeper = TitaniumGatekeeper(config, stats_db)
                raw_espn = get_live_data("NBA")
                spread_ledger = []
                if raw_espn:
                    for event in raw_espn['events']:
                        bets = gatekeeper.audit_game(event, "NBA")
                        spread_ledger.extend(bets)
                
                # 3. DISPLAY RESULTS
                if prop_ledger:
                    st.subheader("🔥 V34 LIVE PROP TARGETS (DraftKings)")
                    st.dataframe(pd.DataFrame(prop_ledger))
                else:
                    st.info("No KOTC Props Found (Defenses Too Strong).")
                    
                if spread_ledger:
                    st.subheader("📊 V34 SPREAD/ML TARGETS")
                    st.dataframe(pd.DataFrame(spread_ledger))
                else:
                    st.info("No Spread/ML Bets Survived Filters.")

    # --- NHL / NCAAB EXECUTION ---
    elif sport in ["NHL", "NCAAB"]:
        if st.button("EXECUTE TITANIUM SEQUENCE"):
            with st.spinner(f"AUDITING {sport} MARKETS..."):
                raw_data = get_live_data(sport)
                if raw_data:
                    gatekeeper = TitaniumGatekeeper(config, None)
                    ledger = []
                    for event in raw_data['events']:
                        bets = gatekeeper.audit_game(event, sport)
                        ledger.extend(bets)
                    
                    if ledger:
                        st.success(f"TARGETS ACQUIRED: {len(ledger)}")
                        df = pd.DataFrame(ledger)
                        cols = ["Sport", "Matchup", "Bet_Type", "Team_Target", "Line", "Price", "Sportsbook", "Logic"]
                        st.dataframe(df[cols], use_container_width=True, hide_index=True)
                    else:
                        st.warning("MARKET EFFICIENT. NO BETS SURVIVED.")
                else:
                    st.error("API CONNECTION FAILED")
    else:
        st.info("PROTOCOL OFFLINE.")

if __name__ == "__main__":
    main()
