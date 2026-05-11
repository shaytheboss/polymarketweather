import streamlit as st
import requests
import datetime

# --- Page Configuration ---
st.set_page_config(
    page_title="Weather Market Predictor",
    page_icon="🌤️",
    layout="centered"
)

st.title("🌤️ Weather Market Predictor")
st.markdown("Calculate the probability of temperature thresholds using **Open-Meteo ECMWF Ensemble** models.")
st.divider()

# --- Input Form ---
with st.container():
    col1, col2 = st.columns(2)
    
    with col1:
        station_city = st.text_input("Station / City *", placeholder="e.g., London Heathrow")
        target_temp = st.number_input("Target Max Temp (°C) *", value=25.0, step=0.1)
        
    with col2:
        target_date = st.date_input("Target Date *", datetime.date.today() + datetime.timedelta(days=1))
        polymarket_url = st.text_input("Polymarket URL (Optional)", placeholder="https://polymarket.com/...")

calculate_btn = st.button("Calculate Probability", type="primary", use_container_width=True)

# --- Core Logic ---
if calculate_btn:
    if not station_city:
        st.warning("Please enter a Station or City name.")
    else:
        with st.spinner("Crunching ensemble models..."):
            try:
                # Step 1: Geocoding (City name to Lat/Lon)
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={station_city}&count=1&language=en&format=json"
                geo_res = requests.get(geo_url).json()
                
                if "results" not in geo_res or len(geo_res["results"]) == 0:
                    st.error("City or Station not found. Please try a different name.")
                    st.stop()
                    
                lat = geo_res["results"][0]["latitude"]
                lon = geo_res["results"][0]["longitude"]
                resolved_name = geo_res["results"][0]["name"]
                country = geo_res["results"][0].get("country", "")

                # Step 2: Fetch Ensemble Data
                date_str = target_date.strftime("%Y-%m-%d")
                ens_url = (
                    f"https://ensemble-api.open-meteo.com/v1/ensemble?"
                    f"latitude={lat}&longitude={lon}&daily=temperature_2m_max&"
                    f"timezone=auto&start_date={date_str}&end_date={date_str}&models=ecmwf_ifs04"
                )
                
                ens_res = requests.get(ens_url).json()

                if "daily" not in ens_res:
                    st.error("Could not fetch ensemble data. The date might be too far in the future.")
                    st.stop()

                # Step 3: Calculate Probability
                daily_data = ens_res["daily"]
                members_temps = []
                
                # Extract all ensemble members dynamically
                for key, value in daily_data.items():
                    if key.startswith("temperature_2m_max_member") and value[0] is not None:
                        members_temps.append(value[0])

                total_members = len(members_temps)
                
                if total_members == 0:
                    st.error("No ensemble data available for this specific date yet.")
                    st.stop()

                hits = sum(1 for temp in members_temps if temp >= target_temp)
                probability = (hits / total_members) * 100
                mean_temp = sum(members_temps) / total_members

                # Step 4: Display Results
                st.success(f"Analysis complete for **{resolved_name}, {country}** on {date_str}")
                
                # Use Streamlit metrics for a clean dashboard look
                m1, m2, m3 = st.columns(3)
                m1.metric(label=f"Prob. (>= {target_temp}°C)", value=f"{probability:.1f}%")
                m2.metric(label="Mean Expected", value=f"{mean_temp:.1f} °C")
                m3.metric(label="Models Run", value=total_members)
                
                # Visual progress bar for the probability
                st.progress(probability / 100.0)

            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
