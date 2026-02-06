import streamlit as st
import pandas as pd
import requests
import json
import os
import datetime
import pytz

# --- TITANIUM KEYVAULT ---
ODDS_API_KEY = "01dc7be6ca076e6b79ac4f54001d142d"

# --- CONFIGURATION ---
st.set_page_config(page_title="TITANIUM V34.12 OMEGA", layout="wide", page_icon="⚡")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {width: 100%; background-color: #00FF00; color: black; font-weight: bold; border: none;}
    .metric-card {background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #00FF00; margin-bottom: 10px;}
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

# --- HELPER: TIME FORMATTER ---
def format_time(iso_string):
    """Converts UTC ISO to CST String."""
    try:
        dt = datetime.datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        cst = dt.astimezone(pytz.timezone("US/Central"))
        return cst.strftime("%I:%M %p")
    except: return "TBD"

# --- HELPER: TEAM MAPPING ---
def get_nba_team_stats(name, db):
    mapping = {"LA Clippers": "L.A. Clippers", "Los Angeles Clippers": "L.A. Clippers", "LA Lakers": "L.A. Lakers", "Los Angeles Lakers": "L.A. Lakers"}
    target = mapping.get(name, name)
    if target in db: return db[target]
    mascot = name.split()[-1]
    for k in db:
        if mascot in k: return db[k]
    return None

# --- ODDS API ENGINE ---
class OddsAPIEngine:
    def __init__(self, api_key):
        self.key = api_key
        self.base = "https://api.the-odds-api.com/v4/sports"
    
    # --- FETCHERS ---
    def fetch_events(self, sport_key):
        url = f"{self.base}/{sport_key}/events?apiKey={self.key}&regions=us&markets=h2h"
        try: return requests.get(url).json()
        except: return []

    def fetch_batch_odds(self, sport_key):
        url = f"{self.base}/{sport_key}/odds?apiKey={self.key}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
        try: return requests.get(url).json()
        except: return []

    def fetch_game_props_nba(self, event_id):
        url = f"{self.base}/basketball_nba/events/{event_id}/odds?apiKey={self.key}&regions=us&markets=h2h,spreads,totals,player_points&oddsFormat=american"
        try: return requests.get(url).json()
        except: return None

    # --- PARSERS ---
    def parse_nba_game(self, data, h_team, a_team, stats_db):
        """NBA: Props + Spread/Total Logic (MAINTAINED)."""
        ledger = []
        bookmakers = data.get('bookmakers', [])
        if not bookmakers: return []
        dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])

        h_st = get_nba_team_stats(h_team, stats_db)
        a_st = get_nba_team_stats(a_team, stats_db)
        if not h_st: h_st = {"DefRtg": 110, "Pace": 98, "NetRtg": 0}
        if not a_st: a_st = {"DefRtg": 110, "Pace": 98, "NetRtg": 0}

        for market in dk_book.get('markets', []):
            # SPREADS
            if market['key'] == 'spreads':
                for outcome in market['outcomes']:
                    team, line, price = outcome['name'], outcome['point'], outcome['price']
                    h_sc = (h_st['NetRtg'] * (h_st['Pace']/100)) + 1.5
                    a_sc = (a_st['NetRtg'] * (a_st['Pace']/100))
                    proj_margin = h_sc - a_sc
                    target_team = h_team if proj_margin > 0 else a_team
                    
                    if team == target_team and abs(line) <= 10.5 and price > -180:
                        ledger.append({
                            "Sport": "NBA", "Type": "Spread", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'],
                            "Audit_Directive": f"AUDIT: Confirm NetRtg Edge ({abs(proj_margin):.1f}). Check Rest."
                        })
            # TOTALS
            elif market['key'] == 'totals':
                for outcome in market['outcomes']:
                    side, line, price = outcome['name'], outcome['point'], outcome['price']
                    combined_pace = h_st['Pace'] + a_st['Pace']
                    if side == "Over" and combined_pace > 202.0:
                        ledger.append({
                            "Sport": "NBA", "Type": "Total", "Target": f"{h_team}/{a_team}", "Line": f"O {line}", "Price": price, "Book": dk_book['title'],
                            "Audit_Directive": f"PACE ALERT: Combined Pace {combined_pace:.1f}."
                        })
                    elif side == "Under" and combined_pace < 194.0:
                        ledger.append({
                            "Sport": "NBA", "Type": "Total", "Target": f"{h_team}/{a_team}", "Line": f"U {line}", "Price": price, "Book": dk_book['title'],
                            "Audit_Directive": f"SLUDGE ALERT: Combined Pace {combined_pace:.1f}."
                        })
            # PROPS
            elif market['key'] == 'player_points':
                for outcome in market['outcomes']:
                    player, side, line, price = outcome['description'], outcome['name'], outcome['point'], outcome['price']
                    if side == "Over" and price > -130 and line > 18.5:
                        msg = ""
                        if h_st['DefRtg'] > 114: msg = f"Target vs {h_team} (DefRtg {h_st['DefRtg']})"
                        elif a_st['DefRtg'] > 114: msg = f"Target vs {a_team} (DefRtg {a_st['DefRtg']})"
                        if msg:
                             ledger.append({
                                "Sport": "NBA", "Type": "Player Prop", "Target": player, "Line": f"Over {line}", "Price": price, "Book": dk_book['title'],
                                "Audit_Directive": f"KOTC: {msg}. Verify Usage."
                            })
        return ledger

    def parse_ncaab_batch(self, games):
        """NCAAB: DIVERSITY & VALUE (Spreads, ML, Totals)."""
        candidates = []
        for game in games:
            bookmakers = game.get('bookmakers', [])
            if not bookmakers: continue
            dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            
            h_team, a_team = game['home_team'], game['away_team']
            time_str = format_time(game['commence_time'])
            matchup = f"{a_team} @ {h_team}"

            for market in dk_book.get('markets', []):
                
                # 1. SPREADS (The Choke Zone)
                if market['key'] == 'spreads':
                    for outcome in market['outcomes']:
                        team, line, price = outcome['name'], outcome['point'], outcome['price']
                        # CLOSERS METRIC (Section XXXIV): -0.5 to -4.5
                        if -4.5 <= line <= -0.5 and price > -180:
                            candidates.append({
                                "Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Spread", 
                                "Target": team, "Line": line, "Price": price, "Book": dk_book['title'],
                                "Audit_Directive": "⚠️ CLOSERS: Small Fav. Audit FT%."
                            })
                            
                # 2. MONEYLINE (Value Dogs)
                elif market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        team, price = outcome['name'], outcome['price']
                        # VALUE DOG: +130 to +250
                        if 130 <= price <= 250:
                            candidates.append({
                                "Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Moneyline", 
                                "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'],
                                "Audit_Directive": "🐶 UPSET WATCH: Verify Home/Away Splits."
                            })
                            
                # 3. TOTALS (Extreme Pace)
                elif market['key'] == 'totals':
                    for outcome in market['outcomes']:
                        side, line, price = outcome['name'], outcome['point'], outcome['price']
                        # SHOOTOUT: > 155
                        if side == "Over" and line > 155.0 and price > -115:
                             candidates.append({
                                "Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Total", 
                                "Target": "Over", "Line": line, "Price": price, "Book": dk_book['title'],
                                "Audit_Directive": "🔥 TRACK MEET: Confirm Pace stats."
                            })
                        # GRIND: < 120
                        elif side == "Under" and line < 120.0 and price > -115:
                             candidates.append({
                                "Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Total", 
                                "Target": "Under", "Line": line, "Price": price, "Book": dk_book['title'],
                                "Audit_Directive": "🧊 SLUDGE FEST: Confirm Def efficiency."
                            })
                        
        # HARD CAP: TOP 12 (Diversity priority)
        return candidates[:12]

    def parse_nhl_batch(self, games):
        """NHL: ML + TOTALS + GUILLOTINE."""
        raw_ledger = []
        
        for game in games:
            bookmakers = game.get('bookmakers', [])
            if not bookmakers: continue
            dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            
            h_team, a_team = game['home_team'], game['away_team']
            if "Penguins" in h_team or "Penguins" in a_team: continue # BAN

            time_str = format_time(game['commence_time'])
            matchup = f"{a_team} @ {h_team}"
            game_id = game['id']

            ml_market = next((m for m in dk_book['markets'] if m['key'] == 'h2h'), None)
            pl_market = next((m for m in dk_book['markets'] if m['key'] == 'spreads'), None) 
            tot_market = next((m for m in dk_book['markets'] if m['key'] == 'totals'), None)

            # MONEYLINE / PUCK LINE
            if ml_market:
                for outcome in ml_market['outcomes']:
                    team, price = outcome['name'], outcome['price']
                    # LOGIC 1: FORCE PL on Heavy Favs (Section XXX)
                    if price < -200 and pl_market: 
                        pl_outcome = next((o for o in pl_market['outcomes'] if o['name'] == team), None)
                        if pl_outcome:
                            raw_ledger.append({
                                "GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Puck Line", 
                                "Target": team, "Line": pl_outcome['point'], "Price": pl_outcome['price'], "Book": dk_book['title'],
                                "Audit_Directive": "SAFETY VALVE: ML expensive."
                            })
                    # LOGIC 2: VALUE ML (Standard #3 Goalie Supremacy)
                    elif (price >= 130) or (-175 <= price <= -140): 
                        raw_ledger.append({
                            "GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Moneyline", 
                            "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'],
                            "Audit_Directive": "VALUE ML: Verify Goalie."
                        })
            
            # TOTALS (NEW)
            if tot_market:
                for outcome in tot_market['outcomes']:
                    side, line, price = outcome['name'], outcome['point'], outcome['price']
                    # ONLY BET IF PRICE IS GOOD (> -105)
                    if price > -105:
                        raw_ledger.append({
                            "GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Total", 
                            "Target": f"{side} {line}", "Line": line, "Price": price, "Book": dk_book['title'],
                            "Audit_Directive": "VALUE TOTAL: Market Inefficiency."
                        })

        # GUILLOTINE: Kill Conflicts (Messy Row Clean-up)
        # If we have ML bets on BOTH sides of same game, delete BOTH.
        clean_ledger = []
        game_bets = {}
        for bet in raw_ledger:
            gid = bet.get('GameID')
            if gid not in game_bets: game_bets[gid] = []
            game_bets[gid].append(bet)

        for gid, bets in game_bets.items():
            # Check for ML conflict
            ml_bets = [b for b in bets if b['Type'] == 'Moneyline']
            has_conflict = len(ml_bets) > 1 
            
            for bet in bets:
                # If conflict exists and this is an ML bet, skip it (kill both sides).
                if has_conflict and bet['Type'] == 'Moneyline':
                    continue
                
                # Clean up dict
                if 'GameID' in bet: del bet['GameID']
                clean_ledger.append(bet)
        
        return clean_ledger

# --- NBA STATS ENGINE ---
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

# --- MAIN UI ---
def main():
    st.sidebar.title("TITANIUM V34.12 OMEGA")
    sport = st.sidebar.selectbox("PROTOCOL SELECTION", ["NBA", "NCAAB", "NHL"])
    
    odds_engine = OddsAPIEngine(ODDS_API_KEY)
    st.title(f"⚡ TITANIUM V34.12 | {sport}")
    
    if st.button(f"EXECUTE {sport} SEQUENCE"):
        with st.spinner(f"SCANNING {sport} MARKETS (DraftKings Live Data)..."):
            
            # NBA
            if sport == "NBA":
                stats_db = fetch_nba_stats()
                events = odds_engine.fetch_events("basketball_nba")
                ledger = []
                if events:
                    for event in events:
                        data = odds_engine.fetch_game_props_nba(event['id'])
                        if data:
                            bets = odds_engine.parse_nba_game(data, event['home_team'], event['away_team'], stats_db)
                            time_str = format_time(event['commence_time'])
                            matchup = f"{event['away_team']} @ {event['home_team']}"
                            for bet in bets:
                                bet['Time'] = time_str
                                bet['Matchup'] = matchup
                                ledger.append(bet)

            # NCAAB (Strict)
            elif sport == "NCAAB":
                raw_data = odds_engine.fetch_batch_odds("basketball_ncaab")
                ledger = odds_engine.parse_ncaab_batch(raw_data)

            # NHL (Efficient)
            elif sport == "NHL":
                raw_data = odds_engine.fetch_batch_odds("icehockey_nhl")
                ledger = odds_engine.parse_nhl_batch(raw_data)
            
            # OUTPUT
            if ledger:
                st.success(f"TARGETS ACQUIRED: {len(ledger)}")
                df = pd.DataFrame(ledger)
                cols = ["Time", "Matchup", "Type", "Target", "Line", "Price", "Book", "Audit_Directive"]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
            else:
                st.warning("MARKET EFFICIENT. NO BETS SURVIVED.")

if __name__ == "__main__":
    main()
