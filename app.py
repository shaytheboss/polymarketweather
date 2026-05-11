import streamlit as st
import requests
import datetime
import re
import pandas as pd
import math

# --- Page Configuration ---
st.set_page_config(
    page_title="Weather Market Predictor",
    page_icon="🌤️",
    layout="centered"
)

def parse_polymarket_url(url):
    """Smart extractor to guess city and date from Polymarket URL"""
    city = None
    target_date = None
    if not url:
        return city, target_date
        
    slug = url.split('/')[-1].lower()
    
    # 1. Extract City
    city_match = re.search(r'(?:will|in|at)-([a-z-]+)-reach', slug)
    if city_match:
        city = city_match.group(1).replace('-', ' ').upper()
    else:
        fallback = re.search(r'(?:in|at)-([a-z]+)', slug)
        if fallback:
            city = fallback.group(1).upper()
            
    # 2. Extract Date (e.g., -on-may-12, -for-october-5)
    month_names = {
        'jan':1, 'january':1, 'feb':2, 'february':2, 'mar':3, 'march':3,
        'apr':4, 'april':4, 'may':5, 'jun':6, 'june':6,
        'jul':7, 'july':7, 'aug':8, 'august':8, 'sep':9, 'september':9,
        'oct':10, 'october':10, 'nov':11, 'november':11, 'dec':12, 'december':12
    }
    
    # Regex searches for a dash, followed by a month name, followed by a dash and 1-2 digits
    date_match = re.search(r'-(' + '|'.join(month_names.keys()) + r')-(\d{1,2})\b', slug)
    if date_match:
        month_str = date_match.group(1)
        day = int(date_match.group(2))
        month = month_names[month_str]
        current_year = datetime.date.today().year
        
        try:
            target_date = datetime.date(current_year, month, day)
        except ValueError:
            pass # Ignore invalid dates like Feb 30
            
    return city, target_date

st.title("🌤️ Weather Market Distribution")
st.markdown("View probability distribution across **all** forecasted temperatures using Ensemble models.")
st.divider()

# --- Input Form ---
with st.container():
    polymarket_url = st.text_input("🔗 Polymarket URL (Paste link to auto-fill city & date)", placeholder="https://polymarket.com/event/...")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        station_city = st.text_input("📍 Station / City (or leave empty if using URL)", placeholder="e.g., Austin or LAX")
    with col2:
        ui_target_date = st.date_input("📅 Target Date (Overridden by URL)", datetime.date.today() + datetime.timedelta(days=1))
    with col3:
        temp_unit = st.selectbox("Unit", ["°F", "°C"])

calculate_btn = st.button("Generate Probability Distribution", type="primary", use_container_width=True)

# --- Core Logic ---
if calculate_btn:
    parsed_city, parsed_date = parse_polymarket_url(polymarket_url)
    
    # URL values override manual UI inputs
    final_city = station_city if station_city else parsed_city
    final_date = parsed_date if parsed_date else ui_target_date

    if not final_city:
        st.error("⚠️ Could not detect a city from the URL. Please enter the Station/City manually.")
    else:
        date_str = final_date.strftime("%Y-%m-%d")
        
        if parsed_date:
            st.info(f"📅 Extracted date from link: **{date_str}**")
            
        with st.spinner(f"Fetching models and calculating distribution for {final_city} on {date_str}..."):
            try:
                # Step 1: Geocoding
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={final_city}&count=1&language=en&format=json"
                geo_res = requests.get(geo_url).json()
                
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    st.error(f"❌ Location '{final_city}' not found. Try a different name.")
                    st.stop()
                    
                lat = geo_res["results"][0]["latitude"]
                lon = geo_res["results"][0]["longitude"]
                resolved_name = geo_res["results"][0]["name"]
                country = geo_res["results"][0].get("country", "")

                # Step 2: Fetch Ensemble Data
                unit_param = "&temperature_unit=fahrenheit" if temp_unit == "°F" else ""
                
                ens_url = (
                    f"https://ensemble-api.open-meteo.com/v1/ensemble?"
                    f"latitude={lat}&longitude={lon}&daily=temperature_2m_max&"
                    f"timezone=auto&past_days=3&forecast_days=14"
                    f"&models=ecmwf_ifs04,gfs_seamless{unit_param}"
                )
                
                ens_res = requests.get(ens_url).json()

                if ens_res.get("error"):
                    st.error(f"❌ API Error: {ens_res.get('reason')}")
                    st.stop()

                if "daily" not in ens_res or "time" not in ens_res["daily"]:
                    st.error("❌ Invalid API response.")
                    st.stop()

                try:
                    date_idx = ens_res["daily"]["time"].index(date_str)
                except ValueError:
                    st.error(f"❌ Date {date_str} is not available in the forecast window.")
                    st.stop()

                daily_data = ens_res["daily"]
                ecmwf_temps = []
                gfs_temps = []
                
                for key, values in daily_data.items():
                    if "temperature_2m_max" in key and "member" in key:
                        val = values[date_idx]
                        if val is not None:
                            if "ecmwf" in key:
                                ecmwf_temps.append(val)
                            elif "gfs" in key:
                                gfs_temps.append(val)
                            else:
                                ecmwf_temps.append(val)

                if len(ecmwf_temps) >= 10:
                    members_temps = ecmwf_temps
                    used_model = "ECMWF (Europe) 🌍"
                elif len(gfs_temps) > 0:
                    members_temps = gfs_temps
                    used_model = "GFS (USA) 🇺🇸"
                else:
                    st.error(f"❌ Models returned NULL for {date_str}. (API may not have generated this data yet)")
                    st.stop()

                total_members = len(members_temps)
                mean_temp = sum(members_temps) / total_members

                # --- NEW FIX: Generate an absolute range for realistic curve ---
                min_t = min(members_temps)
                max_t = max(members_temps)
                
                # Create a uniform scale: floor(min) - 1.5 to ceil(max) + 1.5 in 0.5 increments
                start_t = math.floor(min_t * 2) / 2.0 - 1.5
                end_t = math.ceil(max_t * 2) / 2.0 + 1.5
                
                distribution_data = []
                curr = start_t
                while curr <= end_t:
                    temp_val = round(curr, 1)
                    # How many members predicted a max temp >= this exact threshold?
                    hits = sum(1 for t in members_temps if t >= temp_val)
                    prob = (hits / total_members) * 100
                    
                    distribution_data.append({
                        f"Temperature ({temp_unit})": temp_val, 
                        "Probability (%)": round(prob, 1)
                    })
                    curr += 0.5

                df = pd.DataFrame(distribution_data)

                # Step 3: Display Results
                st.success(f"Generated from **{total_members}** ensemble runs for **{resolved_name}, {country}** on **{date_str}**")
                st.metric(label=f"Mean Expected Temperature", value=f"{mean_temp:.2f} {temp_unit}")
                
                st.divider()
                
                c1, c2 = st.columns([1.5, 1])
                
                with c1:
                    st.subheader("📉 Probability Curve")
                    st.caption("Probability of reaching OR exceeding the temperature")
                    chart_data = df.set_index(f"Temperature ({temp_unit})")
                    st.line_chart(chart_data)
                    
                with c2:
                    st.subheader("📊 Data Table")
                    st.caption("Exact probabilities per threshold")
                    st.dataframe(
                        df.style.format({
                            f"Temperature ({temp_unit})": "{:.1f}", 
                            "Probability (%)": "{:.1f}%"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

            except Exception as e:
                st.error(f"An unexpected Python error occurred: {e}")
