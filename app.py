from flask import Flask, render_template, request
import json
import math
import calendar
import csv

app = Flask(__name__)

# App version
APP_VERSION = "4.5"

# Domyślne wartości
DEFAULT_MOTOR_POWER = 0.3  # Zmieniono z 0.2 na 0.3 kW
DEFAULT_EXPLOITATION_INTENSITY = 0.15  # Zmieniono średnią na 15%
DEFAULT_CLOSE_TIME = "18:00"  # Zmieniono z 20:00 na 18:00

def load_climate_data(filename):
    climate_dict = {}
    coords_dict = {}
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row['City']
            climate_dict[city] = [float(row[m]) for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]]
            coords_dict[city] = (float(row['Lat']), float(row['Lng']))
    return climate_dict, coords_dict

# Ładujemy dane z pliku climate_data.txt
climate_data, cities_coords = load_climate_data("climate_data.txt")

months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

weekday_map = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6
}

YEAR = 2025

def operating_temperature_average(T_out, open_hour, close_hour, A=5, step=0.5):
    total = 0.0
    count = 0
    t = open_hour
    while t < close_hour:
        total += T_out + A * math.sin(math.pi/12 * (t - 5))
        count += 1
        t += step
    return total / count if count > 0 else T_out

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Promień Ziemi w km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    payback_chart_data = None
    temp_table = None
    chosen_city = None

    if request.method == "POST":
        lat_val = request.form.get("lat")
        lng_val = request.form.get("lng")
        if not lat_val or not lng_val:
            return "Error: Please select a location on the map.", 400
        try:
            lat = float(lat_val)
            lng = float(lng_val)
        except ValueError as e:
            return f"Error: Invalid location coordinates: {e}", 400

        nearest_city = None
        min_distance = float('inf')
        for city_name, (city_lat, city_lng) in cities_coords.items():
            d = haversine(lat, lng, city_lat, city_lng)
            if d < min_distance:
                min_distance = d
                nearest_city = city_name
        city = nearest_city
        chosen_city = city

        energy_cost_val = request.form.get("energyCost", "0.25")
        windiness = request.form.get("windiness")
        
        width_val = request.form.get("width")
        height_val = request.form.get("height")
        curtain_flow_val = request.form.get("curtainFlow")
        motor_power_val = request.form.get("motorPower", str(DEFAULT_MOTOR_POWER))
        curtain_price_val = request.form.get("curtainPrice", "900")
        
        indoor_temp_winter_val = request.form.get("indoorTempWinter", "18")
        indoor_temp_summer_val = request.form.get("indoorTempSummer", "22")
        operating_days = request.form.getlist("operatingDays")
        open_time_val = request.form.get("openTime")
        close_time_val = request.form.get("closeTime", DEFAULT_CLOSE_TIME)
        exploitation_intensity_val = request.form.get("exploitationIntensity", str(DEFAULT_EXPLOITATION_INTENSITY))

        if not operating_days:
            operating_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        try:
            width = float(width_val)
            height = float(height_val)
            energy_cost = round(float(energy_cost_val), 2)
            indoor_temp_winter = float(indoor_temp_winter_val)
            indoor_temp_summer = float(indoor_temp_summer_val)
            curtain_flow_m3s = float(curtain_flow_val) / 3600.0
            motor_power = float(motor_power_val)
            curtain_price = float(curtain_price_val)
            exploitation_intensity = float(exploitation_intensity_val)
        except (TypeError, ValueError) as e:
            return f"Error: One of the numeric fields is invalid: {e}", 400

        try:
            open_parts = open_time_val.split(":")
            close_parts = close_time_val.split(":")
            open_hour = int(open_parts[0]) + int(open_parts[1]) / 60.0
            close_hour = int(close_parts[0]) + int(close_parts[1]) / 60.0
            if close_hour <= open_hour:
                return "Error: Closing time must be later than opening time.", 400
        except Exception as e:
            return f"Error: Unable to parse opening/closing times: {e}", 400
    
    return render_template("index.html", version=APP_VERSION, chosen_city=chosen_city)
