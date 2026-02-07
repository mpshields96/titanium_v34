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
st.set_page_config(page_title="TITANIUM V35.2 DIVERSE", layout="wide", page_icon="💀")

# --- CSS STYLING ---
st.markdown("""
<style>
    .stApp {background-color: #0E1117;}
    div.stButton > button {width: 100%; background-color: #FF0000; color: white; font-weight: bold; border: none;}
    .metric-card {background-color: #262730; padding: 15px; border-radius: 8px; border-left: 5px solid #FF0000; margin-bottom: 10px;}
</style>
""", unsafe_allow_html=True)

# --- V35 CONFIG LOADER ---
@st.cache_data
def load_v35_protocol():
    """Parses TITANIUM_V35.json."""
    file_path = "titanium_v35.json"
    if not os.path.exists(file_path): return None
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except: return None

# --- HELPER: TIME FORMATTER ---
def format_time(iso_string):
    """Converts UTC ISO to CST String."""
    try:
        dt = datetime.datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        cst = dt.astimezone(pytz.timezone("US/Central"))
        return cst.strftime("%I:%M %p")
    except: return "TBD"

# --- HELPER: FORCED DIVERSITY DRAFT ---
def force_diversity(ledger, limit):
    """
    Instead of just taking the top X, we round-robin draft
    from different 'Type' buckets to ensure variety.
    """
    if not ledger: return []
    
    # 1. Bucket the bets
    buckets = {}
    for bet in ledger:
        # Group similar types (Spread, Moneyline, Total, Prop)
        b_type = bet['Type']
        if "Spread" in b_type or "Handicap" in b_type or "Run Line" in b_type or "Puck Line" in b_type:
            key = "Spread"
        elif "Moneyline" in b_type or "3-Way" in b_type:
            key = "Moneyline"
        elif "Total" in b_type:
            # Split Overs and Unders
            if "Under" in bet['Target'] or "Under" in bet['Line'] or "U " in bet['Line']: key = "Total_Under"
            else: key = "Total_Over"
        else:
            key = "Prop" # Player Props
        
        if key not in buckets: buckets[key] = []
        buckets[key].append(bet)

    # 2. Sort each bucket by Value
    for k in buckets:
        buckets[k].sort(key=lambda x: x.get('Sort_Val', 0), reverse=True)

    # 3. Round Robin Draft
    final_list = []
    keys = list(buckets.keys())
    
    # Priority Order for Draft
    draft_order = ["Spread", "Total_Over", "Total_Under", "Moneyline", "Prop"]
    
    while len(final_list) < limit:
        added_this_round = False
        for k in draft_order:
            if len(final_list) >= limit: break
            if k in buckets and buckets[k]:
                final_list.append(buckets[k].pop(0))
                added_this_round = True
        
        # If we ran out of specific buckets, just grab whatever is left from the others
        if not added_this_round:
            remaining = []
            for k in buckets: remaining.extend(buckets[k])
            remaining.sort(key=lambda x: x.get('Sort_Val', 0), reverse=True)
            needed = limit - len(final_list)
            final_list.extend(remaining[:needed])
            break
            
    return final_list

# --- TEAM MAPPING ---
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
    
    def fetch_events(self, sport_key):
        url = f"{self.base}/{sport_key}/events?apiKey={self.key}&regions=us&markets=h2h"
        try: return requests.get(url).json()
        except: return []

    def fetch_batch_odds(self, sport_key):
        # REQUEST ALL MARKETS
        url = f"{self.base}/{sport_key}/odds?apiKey={self.key}&regions=us&markets=h2h,spreads,totals&oddsFormat=american"
        try: return requests.get(url).json()
        except: return []

    def fetch_game_props_nba(self, event_id):
        url = f"{self.base}/basketball_nba/events/{event_id}/odds?apiKey={self.key}&regions=us&markets=h2h,spreads,totals,player_points&oddsFormat=american"
        try: return requests.get(url).json()
        except: return None

    def fetch_game_props_nfl(self, event_id):
        url = f"{self.base}/americanfootball_nfl/events/{event_id}/odds?apiKey={self.key}&regions=us&markets=h2h,spreads,totals,player_pass_yds,player_rush_yds,player_reception_yds&oddsFormat=american"
        try: return requests.get(url).json()
        except: return None

    # --- PARSERS ---
    
    def parse_nfl_game(self, data):
        ledger = []
        bookmakers = data.get('bookmakers', [])
        if not bookmakers: return []
        dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
        current_spread_val = 0 
        for market in dk_book.get('markets', []):
            if market['key'] == 'spreads':
                for outcome in market['outcomes']:
                    team, line, price = outcome['name'], outcome['point'], outcome['price']
                    current_spread_val = abs(line)
                    if -180 <= price <= 150:
                        directive = "V35 Audit."
                        sort_val = 50
                        if abs(line) == 3.0 or abs(line) == 7.0: sort_val = 95
                        elif abs(line) in [2.5, 3.5, 6.5, 7.5]: sort_val = 85
                        if sort_val > 60: directive = f"⚠️ KEY NUMBER ({line})."
                        ledger.append({"Sport": "NFL", "Type": "Spread", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": directive, "Sort_Val": sort_val})
            elif market['key'] == 'h2h':
                for outcome in market['outcomes']:
                    team, price = outcome['name'], outcome['price']
                    if -180 <= price <= 150:
                        ledger.append({"Sport": "NFL", "Type": "Moneyline", "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'], "Audit_Directive": "Check Injuries.", "Sort_Val": 60})
            elif market['key'] == 'totals':
                for outcome in market['outcomes']:
                    side, line, price = outcome['name'], outcome['point'], outcome['price']
                    if -120 <= price <= 150:
                        ledger.append({"Sport": "NFL", "Type": "Total", "Target": "Game Total", "Line": f"{side} {line}", "Price": price, "Book": dk_book['title'], "Audit_Directive": "💨 WEATHER CHECK.", "Sort_Val": 55})
            elif market['key'] in ['player_pass_yds', 'player_rush_yds', 'player_reception_yds']:
                prop_type = market['key'].replace('player_', '').replace('_yds', ' Yds').title()
                for outcome in market['outcomes']:
                    player, side, line, price = outcome['description'], outcome['name'], outcome['point'], outcome['price']
                    if -180 <= price <= 150:
                        valid_vol = False
                        if prop_type == "Pass Yds" and line > 225.0: valid_vol = True
                        if prop_type == "Rush Yds" and line > 45.0: valid_vol = True
                        if prop_type == "Reception Yds" and line > 45.0: valid_vol = True
                        if valid_vol:
                            if current_spread_val > 10.5 and side == "Over": continue 
                            directive = "V35 Prop."
                            sort_val = 70
                            if current_spread_val > 10.5 and side == "Under": 
                                directive = "✅ BLOWOUT SHIELD: Under Safe."
                                sort_val = 80
                            if prop_type == "Pass Yds": directive += " Check Wind."
                            ledger.append({"Sport": "NFL", "Type": prop_type, "Target": player, "Line": f"{side} {line}", "Price": price, "Book": dk_book['title'], "Audit_Directive": directive, "Sort_Val": sort_val})
        return ledger

    def parse_nba_game(self, data, h_team, a_team, stats_db):
        ledger = []
        bookmakers = data.get('bookmakers', [])
        if not bookmakers: return []
        dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
        h_st = get_nba_team_stats(h_team, stats_db)
        a_st = get_nba_team_stats(a_team, stats_db)
        if not h_st: h_st = {"DefRtg": 110, "Pace": 98, "NetRtg": 0}
        if not a_st: a_st = {"DefRtg": 110, "Pace": 98, "NetRtg": 0}
        for market in dk_book.get('markets', []):
            if market['key'] == 'spreads':
                for outcome in market['outcomes']:
                    team, line, price = outcome['name'], outcome['point'], outcome['price']
                    h_sc = (h_st['NetRtg'] * (h_st['Pace']/100)) + 1.5
                    a_sc = (a_st['NetRtg'] * (a_st['Pace']/100))
                    proj_margin = h_sc - a_sc
                    target_team = h_team if proj_margin > 0 else a_team
                    if team == target_team and abs(line) <= 12.5 and -180 <= price <= 150:
                        edge = abs(proj_margin) - abs(line)
                        sort_val = 50 + (edge * 10)
                        directive = f"NetRtg Edge ({edge:.1f}). Check Rest."
                        ledger.append({"Sport": "NBA", "Type": "Spread", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": directive, "Sort_Val": sort_val})
            elif market['key'] == 'totals':
                for outcome in market['outcomes']:
                    side, line, price = outcome['name'], outcome['point'], outcome['price']
                    combined_pace = h_st['Pace'] + a_st['Pace']
                    if -180 <= price <= 150:
                        sort_val = 50
                        if side == "Over" and combined_pace > 202.0:
                            sort_val = 70 + (combined_pace - 202)
                            ledger.append({"Sport": "NBA", "Type": "Total", "Target": f"{h_team}/{a_team}", "Line": f"O {line}", "Price": price, "Book": dk_book['title'], "Audit_Directive": f"PACE ALERT: {combined_pace:.1f}.", "Sort_Val": sort_val})
                        elif side == "Under" and combined_pace < 194.0:
                            sort_val = 70 + (194 - combined_pace)
                            ledger.append({"Sport": "NBA", "Type": "Total", "Target": f"{h_team}/{a_team}", "Line": f"U {line}", "Price": price, "Book": dk_book['title'], "Audit_Directive": f"SLUDGE ALERT: {combined_pace:.1f}.", "Sort_Val": sort_val})
            elif market['key'] == 'player_points':
                for outcome in market['outcomes']:
                    player, side, line, price = outcome['description'], outcome['name'], outcome['point'], outcome['price']
                    if side == "Over" and line > 18.5 and -180 <= price <= 150:
                        msg = ""
                        sort_val = 50
                        if h_st['DefRtg'] > 115: 
                            msg = f"vs {h_team} (Def {h_st['DefRtg']})"
                            sort_val = 80
                        elif a_st['DefRtg'] > 115: 
                            msg = f"vs {a_team} (Def {a_st['DefRtg']})"
                            sort_val = 80
                        if msg:
                             ledger.append({"Sport": "NBA", "Type": "Player Prop", "Target": player, "Line": f"Over {line}", "Price": price, "Book": dk_book['title'], "Audit_Directive": f"KOTC: {msg}.", "Sort_Val": sort_val})
        return ledger

    def parse_ncaab_batch(self, games):
        candidates = []
        for game in games:
            bookmakers = game.get('bookmakers', [])
            if not bookmakers: continue
            dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            h_team, a_team = game['home_team'], game['away_team']
            time_str = format_time(game['commence_time'])
            matchup = f"{a_team} @ {h_team}"
            for market in dk_book.get('markets', []):
                # SPREADS
                if market['key'] == 'spreads':
                    for outcome in market['outcomes']:
                        team, line, price = outcome['name'], outcome['point'], outcome['price']
                        if -12.5 <= line <= 12.5 and -180 <= price <= 150:
                            sort_val = 60
                            # Boost Home Favs & Road Dogs
                            if team == h_team and -8.0 <= line <= -2.0: sort_val = 90
                            elif team == a_team and 3.0 <= line <= 8.0: sort_val = 85
                            candidates.append({"Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Spread", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "EFFICIENCY CHECK.", "Sort_Val": sort_val})
                # MONEYLINE (Fixed)
                elif market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        team, price = outcome['name'], outcome['price']
                        if -180 <= price <= 180: 
                            sort_val = 50
                            if 100 <= price <= 160: sort_val = 80 # Value Dog
                            if -150 <= price <= -110: sort_val = 75 # Value Fav
                            candidates.append({"Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Moneyline", "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'], "Audit_Directive": "VALUE ML.", "Sort_Val": sort_val})
                # TOTALS (Fixed)
                elif market['key'] == 'totals':
                    for outcome in market['outcomes']:
                        side, line, price = outcome['name'], outcome['point'], outcome['price']
                        if -180 <= price <= 150:
                            sort_val = 50
                            if side == "Over" and line > 148.0: 
                                sort_val = 80 # Boosted but capped
                                candidates.append({"Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Total", "Target": "Over", "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "🔥 TRACK MEET.", "Sort_Val": sort_val})
                            elif side == "Under" and line < 136.0: 
                                sort_val = 80 # Boosted
                                candidates.append({"Sport": "NCAAB", "Time": time_str, "Matchup": matchup, "Type": "Total", "Target": "Under", "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "🧊 DEFENSIVE WAR.", "Sort_Val": sort_val})
        return candidates

    def parse_nhl_batch(self, games):
        raw_ledger = []
        for game in games:
            bookmakers = game.get('bookmakers', [])
            if not bookmakers: continue
            dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            h_team, a_team = game['home_team'], game['away_team']
            if "Penguins" in h_team or "Penguins" in a_team: continue 
            time_str = format_time(game['commence_time'])
            matchup = f"{a_team} @ {h_team}"
            game_id = game['id']
            # ML
            ml_market = next((m for m in dk_book['markets'] if m['key'] == 'h2h'), None)
            if ml_market:
                for outcome in ml_market['outcomes']:
                    team, price = outcome['name'], outcome['price']
                    if -135 <= price <= 145: 
                        sort_val = 80 - abs(price + 110)
                        raw_ledger.append({"GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Moneyline", "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'], "Audit_Directive": "Verify Goalie.", "Sort_Val": sort_val})
            # TOTALS
            tot_market = next((m for m in dk_book['markets'] if m['key'] == 'totals'), None)
            if tot_market:
                for outcome in tot_market['outcomes']:
                    side, line, price = outcome['name'], outcome['point'], outcome['price']
                    if -130 <= price <= 130: 
                        sort_val = 75 
                        raw_ledger.append({"GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Total", "Target": f"{side} {line}", "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "V35 VARIANCE.", "Sort_Val": sort_val})
            # PUCK LINE (Spread)
            pl_market = next((m for m in dk_book['markets'] if m['key'] == 'spreads'), None)
            if pl_market:
                for outcome in pl_market['outcomes']:
                    team, line, price = outcome['name'], outcome['point'], outcome['price']
                    if -150 <= price <= 160:
                        sort_val = 70
                        if price > 100: sort_val = 85 # Value on PL
                        raw_ledger.append({"GameID": game_id, "Sport": "NHL", "Time": time_str, "Matchup": matchup, "Type": "Puck Line", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "SAFETY VALVE.", "Sort_Val": sort_val})

        # Simple Dedupe
        clean_ledger = []
        seen = set()
        for bet in raw_ledger:
            key = f"{bet['GameID']}_{bet['Type']}_{bet['Target']}"
            if key not in seen:
                del bet['GameID']
                clean_ledger.append(bet)
                seen.add(key)
        return clean_ledger

    def parse_soccer_batch(self, games):
        candidates = []
        for game in games:
            bookmakers = game.get('bookmakers', [])
            if not bookmakers: continue
            dk_book = next((b for b in bookmakers if b['key'] == 'draftkings'), bookmakers[0])
            h_team, a_team = game['home_team'], game['away_team']
            time_str = format_time(game['commence_time'])
            matchup = f"{a_team} @ {h_team}"
            
            for market in dk_book.get('markets', []):
                # 1. 3-Way ML
                if market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        team, price = outcome['name'], outcome['price']
                        if -130 <= price <= 180:
                            sort_val = 70
                            if team == "Draw": sort_val = 85 
                            candidates.append({"Sport": "SOCCER", "Time": time_str, "Matchup": matchup, "Type": "3-Way", "Target": team, "Line": "ML", "Price": price, "Book": dk_book['title'], "Audit_Directive": "Verify xG Form.", "Sort_Val": sort_val})
                # 2. TOTALS
                elif market['key'] == 'totals':
                    for outcome in market['outcomes']:
                        side, line, price = outcome['name'], outcome['point'], outcome['price']
                        if -140 <= price <= 140:
                            sort_val = 75
                            candidates.append({"Sport": "SOCCER", "Time": time_str, "Matchup": matchup, "Type": "Total", "Target": f"{side} {line}", "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "Lineup Check.", "Sort_Val": sort_val})
                # 3. SPREADS
                elif market['key'] == 'spreads':
                    for outcome in market['outcomes']:
                        team, line, price = outcome['name'], outcome['point'], outcome['price']
                        if -150 <= price <= 150:
                            sort_val = 60
                            if abs(line) == 0.5: sort_val = 80
                            candidates.append({"Sport": "SOCCER", "Time": time_str, "Matchup": matchup, "Type": "Spread", "Target": team, "Line": line, "Price": price, "Book": dk_book['title'], "Audit_Directive": "Handicap.", "Sort_Val": sort_val})
        return candidates

@st.cache_data(ttl=3600)
def fetch_nba_stats():
    # Placeholder for live stats or fallback
    return {
        "Boston Celtics": {"NetRtg": 9.5, "Pace": 98.5, "DefRtg": 110.5},
        "Oklahoma City Thunder": {"NetRtg": 8.2, "Pace": 101.0, "DefRtg": 111.0},
        "Denver Nuggets": {"NetRtg": 5.5, "Pace": 97.5, "DefRtg": 113.5}
    }

# --- MAIN UI ---
def main():
    st.sidebar.title("TITANIUM V35.2 DIVERSE")
    sport = st.sidebar.selectbox("PROTOCOL SELECTION", ["NBA", "NFL", "NCAAB", "NHL", "SOCCER"])
    odds_engine = OddsAPIEngine(ODDS_API_KEY)
    st.title(f"💀 TITANIUM V35.2 | {sport}")
    
    # Load V35 Configuration
    v35_config = load_v35_protocol()
    if v35_config: st.sidebar.success("V35 KERNEL: ONLINE")
    else: st.sidebar.error("V35 KERNEL: MISSING")

    if st.button(f"EXECUTE {sport} SEQUENCE"):
        with st.spinner(f"SCANNING {sport} MARKETS (DraftKings Live Data)..."):
            ledger = []
            
            # --- FETCH & PARSE ---
            if sport == "NBA":
                stats_db = fetch_nba_stats()
                events = odds_engine.fetch_events("basketball_nba")
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
                ledger = force_diversity(ledger, 20)

            elif sport == "NFL":
                events = odds_engine.fetch_events("americanfootball_nfl")
                if events:
                    for event in events:
                        data = odds_engine.fetch_game_props_nfl(event['id'])
                        if data:
                            bets = odds_engine.parse_nfl_game(data)
                            time_str = format_time(event['commence_time'])
                            matchup = f"{event['away_team']} @ {event['home_team']}"
                            for bet in bets:
                                bet['Time'] = time_str
                                bet['Matchup'] = matchup
                                ledger.append(bet)
                ledger = force_diversity(ledger, 20)

            elif sport == "NCAAB":
                raw_data = odds_engine.fetch_batch_odds("basketball_ncaab")
                ledger = odds_engine.parse_ncaab_batch(raw_data)
                ledger = force_diversity(ledger, 12)

            elif sport == "NHL":
                raw_data = odds_engine.fetch_batch_odds("icehockey_nhl")
                ledger = odds_engine.parse_nhl_batch(raw_data)
                ledger = force_diversity(ledger, 6)
            
            elif sport == "SOCCER":
                raw_data = odds_engine.fetch_batch_odds("soccer_epl")
                ledger = odds_engine.parse_soccer_batch(raw_data)
                ledger = force_diversity(ledger, 6)
            
            # --- OUTPUT ---
            if ledger:
                st.success(f"TARGETS ACQUIRED: {len(ledger)}")
                df = pd.DataFrame(ledger)
                cols = ["Time", "Matchup", "Type", "Target", "Line", "Price", "Book", "Audit_Directive"]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
            else:
                st.warning("MARKET EFFICIENT. NO BETS SURVIVED.")

if __name__ == "__main__":
    main()
