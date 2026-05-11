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
    """Smart extractor to guess city, temperature and unit from Polymarket URL slug"""
    city, temp, unit = None, None, None
    if not url:
        return city, temp, unit
        
    slug = url.split('/')[-1].lower()
    
    # Extract Temp (e.g., 80f, 25.5c)
    temp_match = re.search(r'(\d+(?:\.\d+)?)(f|c)\b', slug)
    if temp_match:
        temp = float(temp_match.group(1))
        unit = "°F" if temp_match.group(2) == 'f' else "°C"
        
    # Extract City (looks for "in-lax", "at-new-york", etc.)
    city_match = re.search(r'(?:in|at)-([a-z]+(?:-[a-z]+)*?)(?:-reach|-be|-on|-and|-will|\d)', slug)
    if city_match:
        city = city_match.group(1).replace('-', ' ').upper()
    else:
        # Fallback city extraction
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
        station_city = st.text_input("📍 Station / City (Leave empty if using URL)", placeholder="e.g., LAX or London")
        
        # Temp and Unit row
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
    # 1. Parse URL if provided
    parsed_city, parsed_temp, parsed_unit = parse_polymarket_url(polymarket_url)
    
    # 2. Determine final variables (URL overrides manual if manual is empty/default)
    final_city = station_city if station_city else parsed_city
    final_temp = parsed_temp if (polymarket_url and parsed_temp) else target_temp
    final_unit = parsed_unit if (polymarket_url and parsed_unit) else temp_unit

    if not final_city:
        st.error("⚠️ Could not detect a city from the URL. Please enter the Station/City manually.")
    else:
        with st.spinner(f"Fetching coordinates and running models for {final_city}..."):
            try:
                # Step 1: Geocoding (City name to Lat/Lon)
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={final_city}&count=1&language=en&format=json"
                geo_res = requests.get(geo_url).json()
                
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    st.error(f"❌ Location '{final_city}' not found. Try a different name or airport code.")
                    st.stop()
                    
                lat = geo_res["results"][0]["latitude"]
                lon = geo_res["results"][0]["longitude"]
                resolved_name = geo_res["results"][0]["name"]
                country = geo_res["results"][0].get("country", "")

                # Step 2: Fetch Ensemble Data (Both ECMWF and GFS to prevent LAX bug)
                date_str = target_date.strftime("%Y-%m-%d")
                unit_param = "&temperature_unit=fahrenheit" if final_unit == "°F" else ""
                
                ens_url = (
                    f"https://ensemble-api.open-meteo.com/v1/ensemble?"
                    f"latitude={lat}&longitude={lon}&daily=temperature_2m_max&"
                    f"timezone=auto&start_date={date_str}&end_date={date_str}"
                    f"&models=ecmwf_ifs04,gfs_seamless{unit_param}"
                )
                
                ens_res = requests.get(ens_url).json()

                if "daily" not in ens_res:
                    st.error("❌ Could not fetch ensemble data. The date might be too far in the future or past.")
                    st.stop()

                daily_data = ens_res["daily"]
                ecmwf_temps = []
                gfs_temps = []
                
                # Separate models
                for key, value in daily_data.items():
                    if value and len(value) > 0 and value[0] is not None:
                        if "ecmwf_ifs04" in key:
                            ecmwf_temps.append(value[0])
                        elif "gfs_seamless" in key:
                            gfs_temps.append(value[0])

                # Use ECMWF if available, fallback to GFS if ECMWF is empty
                if len(ecmwf_temps) > 0:
                    members_temps = ecmwf_temps
                    used_model = "ECMWF (Europe)"
                elif len(gfs_temps) > 0:
                    members_temps = gfs_temps
                    used_model = "GFS (USA) - Fallback"
                else:
                    st.error("❌ No ensemble data available for this date. (If the date is today or in the past, forecasts are no longer generated).")
                    st.stop()

                total_members = len(members_temps)
                
                # Calculate hits
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
                st.error(f"An unexpected error occurred: {e}")
