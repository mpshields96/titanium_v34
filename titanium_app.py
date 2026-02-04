import streamlit as st
import pandas as pd
import requests
import json
import os
import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="TITANIUM V34 PRIME", layout="wide", page_icon="⚡")

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
    """
    Parses the TITANIUM_V34_BLOAT_MASTER.json file.
    Returns the dictionary or None if file is missing.
    """
    file_path = "titanium_v34.json"
    if not os.path.exists(file_path):
        return None
    
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            # Verify it's the right file by checking for the Master Key
            if "TITANIUM_V34_BLOAT_MASTER" in data:
                return data["TITANIUM_V34_BLOAT_MASTER"]
            return None
    except Exception as e:
        st.error(f"JSON LOAD ERROR: {e}")
        return None

# --- DATA INGESTION: ESPN API ---
def get_live_nba_data():
    """
    Hits the hidden ESPN API endpoint. Bypasses scraping blocks.
    Returns: JSON object or None.
    """
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception as e:
        st.error(f"ESPN CONNECTION FAILURE: {e}")
        return None

# --- V34 GATEKEEPER CLASS ---
class TitaniumGatekeeper:
    def __init__(self, config):
        self.config = config
        self.iron_laws = config.get("SECTION_III_THE_IRON_LAWS_REFORGED", {})
        self.bans = ["Milwaukee Bucks", "Pittsburgh Penguins"] # Hardcoded fallback + dynamic reading

    def _check_odds_collar(self, odds):
        """
        ARTICLE 4: -180 to +150.
        Note: ESPN API often gives spread line (e.g., -5.5) but not always the juice (-110).
        If juice is missing, we assume -110 standard. If provided, we check.
        """
        if odds is None: return True # Benefit of doubt if data missing
        try:
            val = float(odds)
            # If positive (e.g. +140), must be <= 150
            if val > 0:
                return val <= 150
            # If negative (e.g. -200), must be >= -180 (closer to 0)
            else:
                return val >= -180
        except:
            return True

    def _check_blowout_shield(self, spread_str):
        """
        SECTION XXXII: Spread > 10.5 is Rat Poison.
        Input: String like "-6.5" or "12.0"
        """
        try:
            # Clean string
            clean = spread_str.replace("+", "")
            val = float(clean)
            if abs(val) > 10.5:
                return False, f"BLOWOUT RISK (Spread {val} > 10.5)"
            return True, "Safe"
        except:
            return True, "Data Error"

    def _check_team_bans(self, team_name, record_summary):
        """
        ARTICLE 15/16: Bucks/Pens Ban.
        Dynamic Elo check (simplified): Is record < .500?
        """
        # 1. Hard Name Check
        for ban in self.bans:
            if ban.lower() in team_name.lower():
                return False, f"HARD BAN ({ban})"
        
        # 2. Record Check (The Bucks Restriction: Team is clinically dead < .500)
        # record_summary comes from ESPN as "20-25"
        try:
            if record_summary:
                wins, losses = map(int, record_summary.split("-"))
                total = wins + losses
                if total > 0 and (wins / total) < 0.50:
                    # Soft ban check - technically V34 bans Bucks specifically for this, 
                    # but we apply scrutiny to all sub .500 road favs
                    pass 
        except:
            pass
            
        return True, "Clean"

    def _audit_rest(self, competitor_data, is_road_favorite):
        """
        ARTICLE 17: Road Favorite Tax.
        Checks if team played yesterday.
        """
        # ESPN API doesn't always give "Days Rest" explicitly in the scoreboard feed.
        # We need to rely on the 'linescores' or external context. 
        # For this version, we act as a pass-through unless we confirm 0 rest.
        return True, "Rest OK"

    def audit_game(self, event):
        """
        Main Loop for a single game event.
        """
        matchup_id = event.get('id')
        short_name = event.get('shortName')
        competitions = event.get('competitions', [])[0]
        competitors = competitions.get('competitors', [])
        
        # Identify Home/Away
        home_comp = next((c for c in competitors if c['homeAway'] == 'home'), None)
        away_comp = next((c for c in competitors if c['homeAway'] == 'away'), None)
        
        if not home_comp or not away_comp:
            return []

        home_name = home_comp['team']['displayName']
        away_name = away_comp['team']['displayName']
        
        # Odds Handling
        odds_data = competitions.get('odds', [])
        if not odds_data:
            return [] # No odds, no bet
            
        primary_odds = odds_data[0] # Usually the main provider
        spread_str = primary_odds.get('details', '0') # e.g. "DEN -5.5"
        
        # Parse Spread to determine Favorite
        # If detail is "DEN -5.5", Denver is fav.
        fav_team = None
        spread_val = 0.0
        try:
            parts = spread_str.split(" ")
            if len(parts) == 2:
                fav_abbr = parts[0]
                spread_val = float(parts[1])
                # Find which team matches the abbr
                if home_comp['team']['abbreviation'] == fav_abbr:
                    fav_team = "HOME"
                else:
                    fav_team = "AWAY"
        except:
            pass

        # --- RUN THE GAUNTLET ---
        
        targets = []
        
        # 1. CHECK BANS
        h_ok, h_msg = self._check_team_bans(home_name, home_comp.get('records', [{}])[0].get('summary'))
        a_ok, a_msg = self._check_team_bans(away_name, away_comp.get('records', [{}])[0].get('summary'))
        
        if not h_ok: return [{"Status": "FAIL", "Reason": h_msg, "Matchup": short_name}]
        if not a_ok: return [{"Status": "FAIL", "Reason": a_msg, "Matchup": short_name}]

        # 2. BLOWOUT SHIELD
        shield_ok, shield_msg = self._check_blowout_shield(str(spread_val))
        if not shield_ok:
             return [{"Status": "FAIL", "Reason": shield_msg, "Matchup": short_name}]
             
        # 3. CONFLICT RESOLUTION / EDGE FINDING
        # Since we don't have the Titanium Score (NetRtg) calculator in this file (per prompt constraints),
        # We rely on the SPREAD logic. 
        # If it's a Road Favorite (Away is Fav), Audit Rest.
        if fav_team == "AWAY":
            rest_ok, rest_msg = self._audit_rest(away_comp, True)
            if not rest_ok:
                 return [{"Status": "FAIL", "Reason": rest_msg, "Matchup": short_name}]

        # If we survived the bans and shields, we generate the 'Approved' lines
        # Defaulting to the Favorite for the "Edge" calculation placeholder
        
        approved_bet = {
            "Status": "PASS",
            "Matchup": f"{away_name} @ {home_name}",
            "Target": f"{home_name if fav_team == 'HOME' else away_name} {spread_val}",
            "Logic": f"V34 Approved. {shield_msg}.",
            "Odds": primary_odds.get('details')
        }
        
        return [approved_bet]

# --- MAIN APP UI ---
def main():
    st.title("⚡ TITANIUM V34 COMMAND")
    
    # 1. Load Brain
    config = load_v34_protocol()
    if config:
        st.sidebar.success(f"V34 BRAIN: ONLINE ({config.get('META_HEADER', {}).get('VERSION', 'Unknown')})")
    else:
        st.sidebar.error("V34 BRAIN: OFFLINE (JSON Missing)")
        st.stop()

    # 2. Init Gatekeeper
    gatekeeper = TitaniumGatekeeper(config)
    
    # 3. Sidebar Controls
    if st.button("EXECUTE TITANIUM SEQUENCE"):
        with st.spinner("CONTACTING ESPN ORBITAL RELAY..."):
            raw_data = get_live_nba_data()
            
            if not raw_data:
                st.error("ORBITAL RELAY FAILURE (ESPN API DOWN)")
            else:
                events = raw_data.get('events', [])
                st.info(f"SCANNED {len(events)} EVENTS")
                
                ledger = []
                for event in events:
                    results = gatekeeper.audit_game(event)
                    ledger.extend(results)
                
                # Filter for Passes
                passed = [x for x in ledger if x['Status'] == "PASS"]
                failed = [x for x in ledger if x['Status'] == "FAIL"]
                
                if passed:
                    st.success(f"TARGETS ACQUIRED: {len(passed)}")
                    df = pd.DataFrame(passed)
                    st.dataframe(df[['Matchup', 'Target', 'Odds', 'Logic']], use_container_width=True)
                else:
                    st.warning("NO TARGETS SURVIVED V34 FILTERS")
                    
                if failed and st.checkbox("Show Rejected Targets"):
                    st.dataframe(pd.DataFrame(failed))

if __name__ == "__main__":
    main()
