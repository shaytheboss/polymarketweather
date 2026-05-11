import streamlit as st
import requests
import datetime
import re

# --- Page Configuration ---
st.set_page_config(
    page_title="Weather Market Predictor",
    page_icon="🌤️",
    layout="centered"
)

def parse_polymarket_url(url):
    """Smart extractor for Polymarket URLs"""
    city, temp, unit = None, None, None
    if not url:
        return city, temp, unit
        
    slug = url.split('/')[-1].lower()
    
    # Extract Temp (e.g., 80f, 25.5c)
    t_match = re.search(r'(\d+(?:\.\d+)?)(f|c)\b', slug)
    if t_match:
        temp = float(t_match.group(1))
        unit = "°F" if t_match.group(2) == 'f' else "°C"
        
    # Extract City (e.g., will-austin-reach-90f...)
    city_match = re.search(r'(?:will|in|at)-([a-z-]+)-reach', slug)
    if city_match:
        city = city_match.group(1).replace('-', ' ').upper()
    else:
        fallback = re.search(r'(?:in|at)-([a-z]+)', slug)
        if fallback:
            city = fallback.group(1).upper()
            
    return city, temp, unit

st.title("🌤️ Weather Market Predictor")
st.markdown("Calculate probability using **ECMWF & GFS Ensemble** models.")
st.divider()

# --- Input Form ---
with st.container():
    polymarket_url = st.text_input("🔗 Polymarket URL (Paste link here to auto-fill)", placeholder="https://polymarket.com/event/...")
    
    col1, col2 = st.columns(2)
    with col1:
        station_city = st.text_input("📍 Station / City (Leave empty if using URL)", placeholder="e.g., Austin or LAX")
        
        tc1, tc2 = st.columns([2, 1])
        with tc1:
            target_temp = st.number_input("🌡️ Target Max Temp", value=25.0, step=0.1)
        with tc2:
            temp_unit = st.selectbox("Unit", ["°C", "°F"])
            
    with col2:
        target_date = st.date_input("📅 Target Date", datetime.date.today() + datetime.timedelta(days=1))

calculate_btn = st.button("Calculate Probability", type="primary", use_container_width=True)

# --- Core Logic ---
if calculate_btn:
    parsed_city, parsed_temp, parsed_unit = parse_polymarket_url(polymarket_url)
    
    final_city = station_city if station_city else parsed_city
    final_temp = parsed_temp if (polymarket_url and parsed_temp is not None) else target_temp
    final_unit = parsed_unit if (polymarket_url and parsed_unit is not None) else temp_unit

    if not final_city:
        st.error("⚠️ Could not detect a city from the URL. Please enter the Station/City manually.")
    else:
        with st.spinner(f"Fetching coordinates and running models for {final_city}..."):
            try:
                # Step 1: Geocoding
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={final_city}&count=1&language=en&format=json"
                geo_res = requests.get(geo_url).json()
                
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    st.error(f"❌ Location '{final_city}' not found. Try a different name or airport code.")
                    st.stop()
                    
                lat = geo_res["results"][0]["latitude"]
                lon = geo_res["results"][0]["longitude"]
                resolved_name = geo_res["results"][0]["name"]
                country = geo_res["results"][0].get("country", "")

                # Step 2: Fetch Ensemble Data
                date_str = target_date.strftime("%Y-%m-%d")
                unit_param = "&temperature_unit=fahrenheit" if final_unit == "°F" else ""
                
                ens_url = (
                    f"https://ensemble-api.open-meteo.com/v1/ensemble?"
                    f"latitude={lat}&longitude={lon}&daily=temperature_2m_max&"
                    f"timezone=auto&start_date={date_str}&end_date={date_str}"
                    f"&models=ecmwf_ifs04,gfs_seamless{unit_param}"
                )
                
                ens_res = requests.get(ens_url).json()

                # Catch exact API errors from Open-Meteo
                if ens_res.get("error"):
                    st.error(f"❌ Open-Meteo API Error: {ens_res.get('reason')}")
                    st.stop()

                if "daily" not in ens_res or "time" not in ens_res["daily"]:
                    st.error("❌ Could not fetch ensemble data. The API returned an empty or invalid response.")
                    st.stop()

                # Ensure the exact date exists in the returned array
                try:
                    date_idx = ens_res["daily"]["time"].index(date_str)
                except ValueError:
                    st.error(f"❌ Date {date_str} is not available in the model's output window.")
                    st.stop()

                daily_data = ens_res["daily"]
                ecmwf_temps = []
                gfs_temps = []
                
                # Safely extract values for the specific date index
                for key, values in daily_data.items():
                    if "temperature_2m_max_member" in key:
                        val = values[date_idx]
                        if val is not None:
                            if "ecmwf" in key:
                                ecmwf_temps.append(val)
                            elif "gfs" in key:
                                gfs_temps.append(val)
                            else:
                                # Fallback if API drops suffixes
                                ecmwf_temps.append(val)

                # Model Selection Logic
                if len(ecmwf_temps) >= 10:
                    members_temps = ecmwf_temps
                    used_model = "ECMWF (Europe) 🌍"
                elif len(gfs_temps) > 0:
                    members_temps = gfs_temps
                    used_model = "GFS (USA) 🇺🇸"
                elif len(ecmwf_temps) > 0:
                    members_temps = ecmwf_temps
                    used_model = "Default Ensemble"
                else:
                    st.error("❌ Models returned NULL for this specific date. The day might have already started/ended in that timezone, so forecasting is disabled.")
                    st.stop()

                total_members = len(members_temps)
                hits = sum(1 for temp in members_temps if temp >= final_temp)
                probability = (hits / total_members) * 100
                mean_temp = sum(members_temps) / total_members

                # Display Results
                st.success(f"Analysis complete for **{resolved_name}, {country}** using {used_model}")
                st.info(f"🎯 Target Rule: Will it hit **{final_temp}{final_unit}** or higher on **{date_str}**?")
                
                m1, m2, m3 = st.columns(3)
                m1.metric(label="Probability", value=f"{probability:.1f}%")
                m2.metric(label="Mean Expected", value=f"{mean_temp:.1f} {final_unit}")
                m3.metric(label="Models Run", value=total_members)
                
                st.progress(probability / 100.0)

            except Exception as e:
                st.error(f"An unexpected Python error occurred: {e}")
