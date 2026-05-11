import streamlit as st
import requests
import datetime
import re
import pandas as pd

# --- Page Configuration ---
st.set_page_config(
    page_title="Weather Market Predictor",
    page_icon="🌤️",
    layout="centered"
)

def parse_polymarket_url(url):
    """Smart extractor to guess city from Polymarket URL"""
    city = None
    if not url:
        return city
        
    slug = url.split('/')[-1].lower()
    
    # Extract City (e.g., will-austin-reach-90f...)
    city_match = re.search(r'(?:will|in|at)-([a-z-]+)-reach', slug)
    if city_match:
        city = city_match.group(1).replace('-', ' ').upper()
    else:
        fallback = re.search(r'(?:in|at)-([a-z]+)', slug)
        if fallback:
            city = fallback.group(1).upper()
            
    return city

st.title("🌤️ Weather Market Distribution")
st.markdown("View probability distribution across **all** forecasted temperatures using Ensemble models.")
st.divider()

# --- Input Form ---
with st.container():
    polymarket_url = st.text_input("🔗 Polymarket URL (Paste link to auto-fill city)", placeholder="https://polymarket.com/event/...")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        station_city = st.text_input("📍 Station / City (or leave empty if using URL)", placeholder="e.g., Austin or LAX")
    with col2:
        target_date = st.date_input("📅 Target Date", datetime.date.today() + datetime.timedelta(days=1))
    with col3:
        temp_unit = st.selectbox("Unit", ["°F", "°C"])

calculate_btn = st.button("Generate Probability Distribution", type="primary", use_container_width=True)

# --- Core Logic ---
if calculate_btn:
    parsed_city = parse_polymarket_url(polymarket_url)
    final_city = station_city if station_city else parsed_city

    if not final_city:
        st.error("⚠️ Could not detect a city from the URL. Please enter the Station/City manually.")
    else:
        with st.spinner(f"Fetching models and calculating distribution for {final_city}..."):
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
                date_str = target_date.strftime("%Y-%m-%d")
                unit_param = "&temperature_unit=fahrenheit" if temp_unit == "°F" else ""
                
                # THE FIX: Request a wide window (past 3 days, forward 14 days) to prevent timezone boundary NULLs
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

                # Find the exact index of the target date in the wide window array
                try:
                    date_idx = ens_res["daily"]["time"].index(date_str)
                except ValueError:
                    st.error(f"❌ Date {date_str} is not available in the forecast window.")
                    st.stop()

                daily_data = ens_res["daily"]
                ecmwf_temps = []
                gfs_temps = []
                
                # Extract values robustly
                for key, values in daily_data.items():
                    if "temperature_2m_max" in key and "member" in key:
                        val = values[date_idx]
                        if val is not None:
                            if "ecmwf" in key:
                                ecmwf_temps.append(val)
                            elif "gfs" in key:
                                gfs_temps.append(val)
                            else:
                                # Fallback if model name isn't clearly appended
                                ecmwf_temps.append(val)

                # Model Selection
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

                # Calculate Full Distribution
                rounded_temps = [round(t, 1) for t in members_temps]
                unique_temps = sorted(list(set(rounded_temps)))
                
                distribution_data = []
                for temp in unique_temps:
                    hits = sum(1 for t in members_temps if t >= temp)
                    prob = (hits / total_members) * 100
                    distribution_data.append({
                        f"Temperature ({temp_unit})": temp, 
                        "Probability (%)": round(prob, 1)
                    })

                # Create Pandas DataFrame
                df = pd.DataFrame(distribution_data)

                # Step 3: Display Results
                st.success(f"Generated from **{total_members}** ensemble runs for **{resolved_name}, {country}** ({used_model})")
                st.metric(label=f"Mean Expected Temperature", value=f"{mean_temp:.2f} {temp_unit}")
                
                st.divider()
                
                # Display Layout: Chart and Table side-by-side
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
