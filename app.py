from flask import Flask, render_template, request
import json
import math
import calendar
import csv

app = Flask(__name__)

# App version
APP_VERSION = "4.4"

# Funkcja ładująca dane klimatyczne oraz współrzędne z pliku CSV.
# Dane te powinny pochodzić z oficjalnych baz meteorologicznych, np.:
# IMGW (Poland), MeteoFrance (France), DWD (Germany), UK Met Office (UK),
# MétéoSwiss (Switzerland), AEMET (Spain), IPMA (Portugal) itd.
def load_climate_data(filename):
    climate_dict = {}
    coords_dict = {}
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            city = row['City']
            # Odczyt temperatur dla miesięcy (kolumny: Jan, Feb, ..., Dec)
            climate_dict[city] = [float(row[m]) for m in ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]]
            coords_dict[city] = (float(row['Lat']), float(row['Lng']))
    return climate_dict, coords_dict

# Ładujemy dane z pliku climate_data.txt – plik ten należy utworzyć osobno.
climate_data, cities_coords = load_climate_data("climate_data.txt")

months = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

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
    """
    Aproksymacja temperatury operacyjnej poprzez dodanie składnika sinusoidalnego
    (odzwierciedlającego zmianę temperatury w ciągu dnia) do średniej miesięcznej temperatury.
    Wzór:
        T_operating = T_out + A * sin(pi/12 * (t - 5))
    gdzie t przebiega od godziny otwarcia do godziny zamknięcia, z krokiem 'step'.
    Wynik jest uśredniony przez cały okres operacyjny.
    """
    total = 0.0
    count = 0
    t = open_hour
    while t < close_hour:
        total += T_out + A * math.sin(math.pi/12 * (t - 5))
        count += 1
        t += step
    return total / count if count > 0 else T_out

def haversine(lat1, lon1, lat2, lon2):
    """
    Funkcja obliczająca odległość między dwoma punktami na Ziemi
    przy użyciu wzoru haversine.
    """
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
        print("DEBUG: Received form data:", request.form)
        
        # Location – pobieramy współrzędne z mapy
        lat_val = request.form.get("lat")
        lng_val = request.form.get("lng")
        if not lat_val or not lng_val:
            return "Error: Please select a location on the map.", 400
        try:
            lat = float(lat_val)
            lng = float(lng_val)
        except ValueError as e:
            return f"Error: Invalid location coordinates: {e}", 400
        
        # Znajdź najbliższe miasto (na podstawie współrzędnych) z danych z pliku
        nearest_city = None
        min_distance = float('inf')
        for city_name, (city_lat, city_lng) in cities_coords.items():
            d = haversine(lat, lng, city_lat, city_lng)
            if d < min_distance:
                min_distance = d
                nearest_city = city_name
        city = nearest_city  # Wykorzystujemy dane klimatyczne dla najbliższego miasta
        chosen_city = city

        energy_cost_val = request.form.get("energyCost", "0.25")
        windiness = request.form.get("windiness")
        
        # Air Curtain section
        width_val = request.form.get("width")
        height_val = request.form.get("height")
        curtain_flow_val = request.form.get("curtainFlow")
        motor_power_val = request.form.get("motorPower", "0.2")
        curtain_price_val = request.form.get("curtainPrice", "900")
        
        # Building Operation section
        indoor_temp_winter_val = request.form.get("indoorTempWinter", "18")
        indoor_temp_summer_val = request.form.get("indoorTempSummer", "22")
        operating_days = request.form.getlist("operatingDays")
        open_time_val = request.form.get("openTime")
        close_time_val = request.form.get("closeTime")
        exploitation_intensity_val = request.form.get("exploitationIntensity", "0.25")
        
        if not operating_days:
            operating_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        required_fields = {
            "width": width_val,
            "height": height_val,
            "energyCost": energy_cost_val,
            "indoorTempWinter": indoor_temp_winter_val,
            "indoorTempSummer": indoor_temp_summer_val,
            "curtainFlow": curtain_flow_val,
            "motorPower": motor_power_val,
            "curtainPrice": curtain_price_val,
            "openTime": open_time_val,
            "closeTime": close_time_val,
            "exploitationIntensity": exploitation_intensity_val
        }
        for key, value in required_fields.items():
            if value is None or value.strip() == "":
                return f"Error: The field '{key}' is required.", 400
        
        try:
            width = float(width_val)
            height = float(height_val)
            energy_cost = round(float(energy_cost_val), 2)
            indoor_temp_winter = float(indoor_temp_winter_val)
            indoor_temp_summer = float(indoor_temp_summer_val)
            # Air curtain flow: domyślnie 2500 m³/h
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
            daily_operating_hours = close_hour - open_hour
        except Exception as e:
            return f"Error: Unable to parse opening/closing times: {e}", 400
        
        # Obliczanie miesięcznych godzin operacyjnych
        monthly_operating_hours = []
        for m in range(1, 13):
            num_operating_days = 0
            cal = calendar.monthcalendar(YEAR, m)
            for week in cal:
                for i, day in enumerate(week):
                    if day != 0:
                        weekday_name = list(weekday_map.keys())[i]
                        if weekday_name in operating_days:
                            num_operating_days += 1
            monthly_operating_hours.append(daily_operating_hours * num_operating_days)
        
        effective_monthly_hours = [int(round(h * exploitation_intensity)) for h in monthly_operating_hours]
        
        wind_factor = {"weak": 1.0, "medium": 1.1, "strong": 1.2}.get(windiness, 1.1)
        
        rho = 1.2     
        g = 9.81      
        cp = 1005     
        Cd = 0.6
        
        energy_without = []
        energy_with = []
        monthly_savings = []
        motor_energy_list = []
        total_energy_without = 0
        total_energy_with = 0
        total_savings = 0
        
        temp_table = []
        operating_temps = []
        
        # Pobieramy dane klimatyczne dla wybranego miasta
        outside_temps = climate_data.get(city, None)
        if not outside_temps:
            outside_temps = [10] * 12
        
        for i, month in enumerate(months):
            T_out = outside_temps[i]
            T_operating = operating_temperature_average(T_out, open_hour, close_hour, A=5, step=0.5)
            operating_temps.append(int(round(T_operating)))
            if T_operating < indoor_temp_winter:
                chosen_indoor = indoor_temp_winter
                season_info = "Automatic: winter season temperature selected"
            elif T_operating > indoor_temp_summer:
                chosen_indoor = indoor_temp_summer
                season_info = "Automatic: summer season temperature selected"
            else:
                chosen_indoor = T_operating
                season_info = "Transitional season"
            
            deltaT = abs(chosen_indoor - T_operating)
            T_inside_K = chosen_indoor + 273.15
            
            delta_p = rho * g * height * (deltaT / T_inside_K)
            A_area = width * height
            Q_natural = Cd * A_area * math.sqrt((2 * delta_p) / rho)
            Q_corrected = Q_natural * wind_factor
            
            W_no = Q_corrected * rho * cp * deltaT
            E_no = (W_no / 1000) * effective_monthly_hours[i]
            
            eta = min(curtain_flow_m3s / Q_corrected, 1.0) if Q_corrected > 0 else 0
            Q_effective = Q_corrected * (1 - eta)
            W_curtain = Q_effective * rho * cp * deltaT
            E_curtain = (W_curtain / 1000) * effective_monthly_hours[i]
            
            savings = E_no - E_curtain
            
            motor_energy = effective_monthly_hours[i] * motor_power
            motor_energy_list.append(int(round(motor_energy)))
            
            energy_without.append(int(round(E_no)))
            energy_with.append(int(round(E_curtain)))
            monthly_savings.append(int(round(savings)))
            
            total_energy_without += E_no
            total_energy_with += E_curtain
            total_savings += savings
            
            temp_table.append({
                "month": month,
                "temperature": int(round(T_out)),
                "operating_temperature": int(round(T_operating)),
                "indoor_temperature": int(round(chosen_indoor)),
                "season_warning": season_info
            })
        
        annual_motor_energy = sum(motor_energy_list)
        annual_energy_with_motor = total_energy_with + annual_motor_energy
        
        annual_cost_without = int(round(total_energy_without * energy_cost))
        annual_cost_with = int(round(total_energy_with * energy_cost))
        annual_cost_motor = int(round(annual_motor_energy * energy_cost))
        annual_cost_with_motor = annual_cost_with + annual_cost_motor
        
        annual_savings_energy = int(round(total_energy_without - annual_energy_with_motor))
        annual_savings_cost = int(round(annual_cost_without - annual_cost_with_motor))
        
        payback_period = (curtain_price / annual_savings_cost) if annual_savings_cost > 0 else None
        
        result = {
            "total_savings": int(round(total_savings)),
            "energy_without": energy_without,
            "energy_with": energy_with,
            "motor_energy": motor_energy_list,
            "months": months,
            "monthly_savings": monthly_savings,
            "monthly_operating_hours": effective_monthly_hours,
            "annual_energy_without": int(round(total_energy_without)),
            "annual_cost_without": f"{annual_cost_without} EUR",
            "annual_energy_with": int(round(total_energy_with)),
            "annual_cost_with": f"{annual_cost_with} EUR",
            "annual_motor_energy": int(round(annual_motor_energy)),
            "annual_cost_motor": f"{annual_cost_motor} EUR",
            "annual_energy_with_motor": int(round(annual_energy_with_motor)),
            "annual_cost_with_motor": f"{annual_cost_with_motor} EUR",
            "annual_savings_energy": annual_savings_energy,
            "annual_savings_cost": f"{annual_savings_cost} EUR",
            "payback_period": payback_period
        }
        
        chart_data = json.dumps({
            "months": months,
            "without": energy_without,
            "with": [energy_with[i] + motor_energy_list[i] for i in range(len(months))]
        })
        
        years = list(range(0, 16))
        cumulative_cost_without = [annual_cost_without * y for y in years]
        cumulative_cost_with = [curtain_price + (annual_cost_with_motor * y) for y in years]
        payback_chart_data = json.dumps({
            "years": years,
            "without": cumulative_cost_without,
            "with": cumulative_cost_with,
            "payback": payback_period
        })
    
    return render_template("index.html", result=result, chart_data=chart_data,
                           payback_chart_data=payback_chart_data, temp_table=temp_table,
                           chosen_city=chosen_city, version=APP_VERSION)

if __name__ == "__main__":
    app.run(debug=True)
