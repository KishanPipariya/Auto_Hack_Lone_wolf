import streamlit as st
import requests
import json
import time
import os
from datetime import datetime

# --- Configuration ---
# Prioritize Environment Variable -> Secrets -> Localhost
if "BACKEND_URL" in st.secrets:
    API_URL = st.secrets["BACKEND_URL"]
else:
    API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Travel Agent Demo", page_icon="✈️", layout="wide")

# --- CSS / Aesthetics ---
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        height: 3em;
    }
    .success-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f0fdf4;
        color: #15803d;
        border: 1px solid #bbf7d0;
    }
    .error-box {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #fef2f2;
        color: #b91c1c;
        border: 1px solid #fecaca;
    }
</style>
""", unsafe_allow_html=True)

# --- Session State Management ---
if 'token' not in st.session_state:
    st.session_state.token = None
if 'view' not in st.session_state:
    st.session_state.view = 'planner' # planner, history

# --- API Helpers ---
def api_request(method, endpoint, data=None, token=None):
    headers = {}
    if token:
        headers['Authorization'] = f"Bearer {token}"
    
    url = f"{API_URL}{endpoint}"
    try:
        if method == 'POST':
            # Handle form-encoded for token, json for others
            if endpoint == '/auth/token':
                response = requests.post(url, data=data)
            else:
                response = requests.post(url, json=data, headers=headers)
        elif method == 'GET':
            response = requests.get(url, headers=headers)
        
        return response
    except requests.exceptions.ConnectionError:
        st.error(f"❌ Could not connect to backend at {API_URL}. Is the server running?")
        return None

def stream_planner(payload):
    url = f"{API_URL}/plan_stream"
    try:
        with requests.post(url, json=payload, stream=True) as r:
            if r.status_code != 200:
                yield f"Error: {r.status_code} {r.text}"
                return

            buffer = ""
            for chunk in r.iter_content(chunk_size=None):
                if chunk:
                    text = chunk.decode('utf-8')
                    buffer += text
                    
                    # Split logic similar to frontend
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        if not line.strip(): continue
                        
                        try:
                            msg = json.loads(line)
                            if msg['type'] == 'status':
                                yield f"🔄 {msg['message']}\n\n"
                            elif msg['type'] == 'result':
                                # We yield the full markdown result
                                if msg['data'].get('valid'):
                                    # Convert JSON itinerary to Markdown
                                    data = msg['data']
                                    md = f"# 🌍 Trip to {data['city']}\n\n"
                                    for day in data['days']:
                                        md += f"## Day {day['day_number']}\n"
                                        for act in day['activities']:
                                            md += f"**{act['name']}** ({act.get('duration_str', '')})\n"
                                            md += f"{act['description']}\n"
                                            md += f"*Cost: ${act.get('cost', 0)}*\n\n"
                                    md += f"**Total Cost: ${sum(d['activities_cost'] for d in data.get('days',[])) if 'days' in data else 'N/A'}**"
                                    yield md
                                else:
                                    yield f"⚠️ Validation Error: {msg['data'].get('validation_error')}"
                            elif msg['type'] == 'error':
                                yield f"❌ Error: {msg['message']}"
                        except Exception:
                            pass
    except Exception as e:
        yield f"Stream Error: {e}"

# --- Authentication Sidebar ---
def render_auth():
    with st.sidebar:
        st.header("👤 Authentication")
        
        if st.session_state.token:
            st.success("Logged In")
            if st.button("Logout"):
                st.session_state.token = None
                st.rerun()
            return

        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Login", type="primary"):
                # Form data for OAuth2
                data = {'username': email, 'password': password}
                res = api_request('POST', '/auth/token', data=data)
                if res and res.status_code == 200:
                    st.session_state.token = res.json()['access_token']
                    st.success("Login Successful!")
                    st.rerun()
                elif res:
                    st.error(res.text)

        with tab2:
            reg_email = st.text_input("Email", key="reg_email")
            reg_pass = st.text_input("Password", type="password", key="reg_pass")
            if st.button("Register"):
                data = {'email': reg_email, 'password': reg_pass}
                res = api_request('POST', '/auth/register', data=data)
                if res and res.status_code == 200:
                    st.success("Registered! You can now login.")
                elif res:
                    st.error(res.text)

# --- Views ---
def render_planner():
    st.title("✈️ Plan Your Trip")
    
    with st.form("plan_form"):
        col1, col2 = st.columns(2)
        with col1:
            dest = st.text_input("Destination", placeholder="Paris, Tokyo, New York...")
            days = st.number_input("Duration (Days)", min_value=1, max_value=14, value=3)
        with col2:
            budget = st.number_input("Budget ($)", min_value=100, step=100, value=1000)
            start_date = st.date_input("Start Date", value=None)
        
        interests = st.multiselect("Interests", 
            ["History", "Art", "Food", "Nature", "Shopping", "Adventure"],
            default=["Food", "History"]
        )
        custom_interests = st.text_input("Other Interests (comma separated)")
        
        submitted = st.form_submit_button("Generate Itinerary", type="primary")
        
        if submitted:
            if not dest:
                st.warning("Please enter a destination.")
                return

            final_interests = interests.copy()
            if custom_interests:
                final_interests.extend([x.strip() for x in custom_interests.split(',') if x.strip()])

            payload = {
                "city": dest,
                "days": days,
                "budget": budget,
                "start_date": str(start_date) if start_date else None,
                "interests": final_interests
            }

            st.write("---")
            st.subheader("Generating Itinerary...")
            
            # Simple streaming simulation via container
            result_container = st.empty()
            full_text = ""
            
            # Streaming Logic using generator
            # Streamlit's write_stream is new, let's use a robust loop
            for chunk in stream_planner(payload):
                if "🌍" in chunk: # Result detected
                     st.markdown(chunk) # Render final result
                else:
                    st.text(chunk.strip()) # Status updates

def render_history():
    st.title("📜 Trip History")
    if not st.session_state.token:
        st.warning("Please login to view history.")
        return

    res = api_request('GET', '/history', token=st.session_state.token)
    if res and res.status_code == 200:
        trips = res.json()
        if not trips:
            st.info("No trips saved yet.")
            return

        for trip in trips:
            with st.expander(f"🌍 {trip['city']} ({trip['days']} Days) - {trip['created_at'][:10]}"):
                # Need to fetch details
                if st.button("Load Details", key=f"btn_{trip['id']}"):
                    detail_res = api_request('GET', f"/history/{trip['id']}", token=st.session_state.token)
                    if detail_res and detail_res.status_code == 200:
                        data = detail_res.json()
                        st.json(data) # Or format nicely
                    else:
                        st.error("Could not load details")
    elif res:
        st.error(f"Error: {res.status_code}")

# --- Main App ---
render_auth()

# Top Nav (Radio or Buttons)
view = st.radio("Navigation", ["Plan Trip", "My Trips"], horizontal=True, label_visibility="collapsed")

if view == "Plan Trip":
    render_planner()
else:
    render_history()
