import math
import calendar
import datetime
import json
import os
from flask import Flask, render_template, request, make_response
import pdfkit  # biblioteka do generowania PDF

app = Flask(__name__)
APP_VERSION = "9.0"  # Zaktualizowana wersja

# Lista miesięcy
months = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# Mapa dni tygodnia
weekday_map = {
    "Monday": 0, "Tuesday": 1, "Wednesday": 2,
    "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6
}

YEAR = 2025
EMISSION_FACTOR = 0.233  # kg CO₂/kWh

# Pliki danych
CITIES_FILE = "cities.txt"
TRANSLATIONS_FILE = "translations.txt"

def load_cities_data():
    if not os.path.exists(CITIES_FILE):
        raise Exception(f"Plik {CITIES_FILE} nie istnieje. Utwórz go zgodnie z instrukcjami.")
    with open(CITIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

cities_data = load_cities_data()

def load_translations():
    if not os.path.exists(TRANSLATIONS_FILE):
        raise Exception(f"Plik {TRANSLATIONS_FILE} nie istnieje. Utwórz go zgodnie z instrukcjami.")
    with open(TRANSLATIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

translations_data = load_translations()

def translate(text_key, lang, **kwargs):
    trans = translations_data.get(lang, translations_data["English"])
    text = trans.get(text_key, text_key)
    if kwargs:
        text = text.format(**kwargs)
    return text

@app.context_processor
def inject_translate():
    return dict(translate=translate)

languages = list(translations_data.keys())
currencies = ["EUR"]

# 8-stopniowa skala wiatru – wartość pobierana z formularza (jako string) przekształcana do mnożnika
wind_scale = {
    "0": 0.0,    # brak wiatru
    "1": 0.25,
    "2": 0.5,
    "3": 0.75,
    "4": 1.0,    # medium (domyślnie)
    "5": 1.25,
    "6": 1.5,
    "7": 1.75
}

def smooth_data(data, window=3):
    smoothed = []
    n = len(data)
    half = window // 2
    for i in range(n):
        start = max(0, i - half)
        end = min(n, i + half + 1)
        smoothed.append(round(sum(data[start:end]) / (end - start), 1))
    return smoothed

def get_reference_hourly_data_for_location(user_lat, user_lon):
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def find_nearest_city(user_lat, user_lon, cities):
        nearest_city = None
        min_dist = float('inf')
        for city, info in cities.items():
            dist = haversine(user_lat, user_lon, info["lat"], info["lon"])
            if dist < min_dist:
                min_dist = dist
                nearest_city = city
        return nearest_city, cities[nearest_city]

    chosen_city, city_info = find_nearest_city(user_lat, user_lon, cities_data)
    baseline = city_info["baseline"]
    amp = city_info["amplitude"]
    wind_baseline = city_info.get("wind_baseline")
    wind_amp = city_info.get("wind_amplitude")
    
    temp_data = {}
    wind_data = {}
    A_day_temp = 1.0
    A_day_wind = 0.5
    for m in range(1, 13):
        num_days = calendar.monthrange(YEAR, m)[1]
        temp_data[m] = {}
        wind_data[m] = {}
        offset = num_days / 2.0
        for day in range(1, num_days + 1):
            temp_data[m][day] = {}
            wind_data[m][day] = {}
            daily_temp = baseline[m-1] + A_day_temp * math.sin(2 * math.pi * (day - offset) / num_days)
            daily_wind = wind_baseline[m-1] + A_day_wind * math.sin(2 * math.pi * (day - offset) / num_days)
            for hour in range(24):
                temp_hourly = daily_temp + amp[m-1] * math.sin(2 * math.pi * (hour - 6) / 24)
                wind_hourly = daily_wind + wind_amp[m-1] * math.sin(2 * math.pi * (hour - 6) / 24)
                temp_data[m][day][hour] = round(temp_hourly, 1)
                wind_data[m][day][hour] = round(wind_hourly, 1)
    return temp_data, wind_data, chosen_city, amp

def generate_hourly_reference_year(ref_data):
    hourly_data = []
    for m in range(1, 13):
        num_days = calendar.monthrange(YEAR, m)[1]
        for day in range(1, num_days + 1):
            for hour in range(24):
                dt = datetime.datetime(YEAR, m, day, hour, 0)
                temp = ref_data[m][day].get(hour)
                hourly_data.append((dt, temp))
    return hourly_data

def generate_hourly_wind_year(wind_data):
    hourly_wind = []
    for m in range(1, 13):
        num_days = calendar.monthrange(YEAR, m)[1]
        for day in range(1, num_days + 1):
            for hour in range(24):
                dt = datetime.datetime(YEAR, m, day, hour, 0)
                wind = wind_data[m][day].get(hour)
                hourly_wind.append((dt, wind))
    return hourly_wind

def compute_weekly_averages(hourly_data):
    weekly = {}
    for dt, value in hourly_data:
        if value is None:
            continue
        week = dt.isocalendar()[1]
        if week not in weekly:
            weekly[week] = []
        weekly[week].append(value)
    weekly_avg = {}
    for week, values in weekly.items():
        weekly_avg[week] = round(sum(values) / len(values), 1)
    weeks = sorted(weekly_avg.keys())
    avg = [weekly_avg[w] for w in weeks]
    return json.dumps({"weeks": weeks, "avg": avg})

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    chart_data = None
    payback_chart_data = None
    weekly_chart_data = None
    weekly_wind_chart_data = None
    temp_table = None
    chosen_station = None
    selected_language = "English"

    if request.method == "POST":
        lat_val = request.form.get("lat")
        lng_val = request.form.get("lng")
        if not lat_val or not lng_val:
            return "<script>alert('Brakuje danych: wybierz lokalizację na mapie.');document.getElementById('map').scrollIntoView({behavior: 'smooth'});window.history.back();</script>", 400
        try:
            user_lat = float(lat_val)
            user_lon = float(lng_val)
        except ValueError as e:
            return f"Error: Invalid coordinates: {e}", 400

        selected_language = request.form.get("language", "English")
        temp_data, wind_data, chosen_city, amp = get_reference_hourly_data_for_location(user_lat, user_lon)
        chosen_station = chosen_city
        hourly_temp = generate_hourly_reference_year(temp_data)
        hourly_wind = generate_hourly_wind_year(wind_data)
        if all(temp is None for dt, temp in hourly_temp):
            return "Error: Brak danych temperatur referencyjnych", 500

        weekly_chart_data = compute_weekly_averages(hourly_temp)
        weekly_wind_chart_data = compute_weekly_averages(hourly_wind)
        # Wygładzamy dane wiatru, by wykres był bardziej równomierny
        weekly_wind_dict = json.loads(weekly_wind_chart_data)
        weekly_wind_dict["avg"] = smooth_data(weekly_wind_dict["avg"], window=3)
        weekly_wind_chart_data = json.dumps(weekly_wind_dict)

        energy_cost = round(float(request.form.get("energyCost", "0.25")), 2)
        # Pobieramy wartość z 8-stopniowej skali
        windiness = request.form.get("windiness", "4")
        wind_multiplier = wind_scale.get(windiness, 1.0)
        width = float(request.form.get("width"))
        height = float(request.form.get("height"))
        curtain_flow_m3s = float(request.form.get("curtainFlow")) / 3600.0
        motor_power = float(request.form.get("motorPower", "0.3"))
        curtain_price = float(request.form.get("curtainPrice", "1100"))
        indoor_temp_winter = float(request.form.get("indoorTempWinter", "18"))
        indoor_temp_summer = float(request.form.get("indoorTempSummer", "22"))
        operating_days = request.form.getlist("operatingDays")
        open_time_val = request.form.get("openTime")
        close_time_val = request.form.get("closeTime")
        exploitation_intensity = float(request.form.get("exploitationIntensity", "0.15"))
        if not operating_days:
            operating_days = list(weekday_map.keys())

        try:
            open_hour = int(open_time_val.split(":")[0]) + int(open_time_val.split(":")[1]) / 60.0
            close_hour = int(close_time_val.split(":")[0]) + int(close_time_val.split(":")[1]) / 60.0
            if close_hour <= open_hour:
                return "Error: Closing time must be later than opening time.", 400
            operating_period_duration = close_hour - open_hour
        except Exception as e:
            return f"Error: Unable to parse times: {e}", 400

        monthly_operating_hours = []
        for m in range(1, 13):
            num_operating_days = 0
            cal = calendar.monthcalendar(YEAR, m)
            for week in cal:
                for i, day in enumerate(week):
                    if day != 0 and list(weekday_map.keys())[i] in operating_days:
                        num_operating_days += 1
            monthly_operating_hours.append(num_operating_days * operating_period_duration)
        effective_monthly_hours = [int(round(h * exploitation_intensity)) for h in monthly_operating_hours]

        # Obliczenia dla temperatury i wiatru
        monthly_temp = {m: [] for m in range(1, 13)}
        operating_temp = {m: [] for m in range(1, 13)}
        monthly_wind = {m: [] for m in range(1, 13)}
        operating_wind = {m: [] for m in range(1, 13)}
        for dt, temp in hourly_temp:
            if temp is None:
                continue
            m = dt.month
            monthly_temp[m].append(temp)
            t_val = dt.hour + dt.minute/60.0
            if open_hour <= t_val < close_hour:
                operating_temp[m].append(temp)
        for dt, wind in hourly_wind:
            if wind is None:
                continue
            m = dt.month
            monthly_wind[m].append(wind)
            t_val = dt.hour + dt.minute/60.0
            if open_hour <= t_val < close_hour:
                operating_wind[m].append(wind)
        monthly_avg_temps = []
        operating_avgs = []
        monthly_avg_wind = []
        operating_avg_wind = []
        temp_table = []
        for m in range(1, 13):
            full_avg = round(sum(monthly_temp[m]) / len(monthly_temp[m]), 1) if monthly_temp[m] else None
            op_avg = round(sum(operating_temp[m]) / len(operating_temp[m]), 1) if operating_temp[m] else None
            wind_avg = round(sum(monthly_wind[m]) / len(monthly_wind[m]), 1) if monthly_wind[m] else None
            op_wind_avg = round(sum(operating_wind[m]) / len(operating_wind[m]), 1) if operating_wind[m] else None
            monthly_avg_temps.append(full_avg)
            operating_avgs.append(op_avg)
            monthly_avg_wind.append(wind_avg)
            operating_avg_wind.append(op_wind_avg)
            amp_value = amp[m-1]
            if full_avg is None or op_avg is None or op_wind_avg is None:
                temp_table.append({
                    "month": months[m-1],
                    "monthly_avg": "brak danych",
                    "wind_avg": "brak danych",
                    "operating_avg": "brak danych",
                    "operating_wind": "brak danych",
                    "indoor_temp": "brak danych",
                    "season_info": f"Amplitude: {amp_value}°C"
                })
            else:
                if op_avg < indoor_temp_winter:
                    chosen_indoor = indoor_temp_winter
                    season_info = "Automatic: winter season temperature selected"
                elif op_avg > indoor_temp_summer:
                    chosen_indoor = indoor_temp_summer
                    season_info = "Automatic: summer season temperature selected"
                else:
                    chosen_indoor = op_avg
                    season_info = "Transitional season"
                season_info += f" (Temp Amplitude: {amp_value}°C)"
                temp_table.append({
                    "month": months[m-1],
                    "monthly_avg": f"{full_avg:.1f}",
                    "wind_avg": f"{wind_avg:.1f}",
                    "operating_avg": f"{op_avg:.1f}",
                    "operating_wind": f"{op_wind_avg:.1f}",
                    "indoor_temp": f"{chosen_indoor:.1f}",
                    "season_info": season_info
                })

        # Obliczenia zużycia energii i śladu węglowego
        if all(val is not None for val in operating_avgs):
            energy_without = []
            energy_with = []
            monthly_savings = []
            motor_energy_list = []
            monthly_carbon_savings = []
            for i in range(1, 13):
                T_operating = operating_avgs[i-1]
                if T_operating < indoor_temp_winter:
                    chosen_indoor = indoor_temp_winter
                elif T_operating > indoor_temp_summer:
                    chosen_indoor = indoor_temp_summer
                else:
                    chosen_indoor = T_operating
                deltaT = abs(chosen_indoor - T_operating)
                T_inside_K = chosen_indoor + 273.15
                delta_p = 1.2 * 9.81 * height * (deltaT / T_inside_K)
                A_area = width * height
                Q_natural = 0.6 * A_area * math.sqrt((2 * delta_p) / 1.2)
                Q_corrected = Q_natural * wind_multiplier
                W_no = Q_corrected * 1.2 * 1005 * deltaT
                E_no = (W_no / 1000) * effective_monthly_hours[i-1]
                eta = min(curtain_flow_m3s / Q_corrected, 1.0) if Q_corrected > 0 else 0
                Q_effective = Q_corrected * (1 - eta)
                W_curtain = Q_effective * 1.2 * 1005 * deltaT
                E_curtain = (W_curtain / 1000) * effective_monthly_hours[i-1]
                savings = E_no - E_curtain
                motor_energy = effective_monthly_hours[i-1] * motor_power
                motor_energy_list.append(int(round(motor_energy)))
                energy_without.append(int(round(E_no)))
                energy_with.append(int(round(E_curtain)))
                monthly_savings.append(int(round(savings)))
                # Obliczamy miesięczną oszczędność śladu węglowego (kg CO₂)
                monthly_carbon = round(savings * EMISSION_FACTOR, 1)
                monthly_carbon_savings.append(monthly_carbon)
            annual_motor_energy = sum(motor_energy_list)
            total_energy_without = sum(energy_without)
            total_energy_with = sum(energy_with)
            annual_energy_with_motor = total_energy_with + annual_motor_energy
            annual_cost_without = int(round(total_energy_without * energy_cost))
            annual_cost_with = int(round(total_energy_with * energy_cost))
            annual_cost_motor = int(round(annual_motor_energy * energy_cost))
            annual_cost_with_motor = annual_cost_with + annual_cost_motor
            annual_savings_energy = int(round(total_energy_without - annual_energy_with_motor))
            annual_savings_cost = int(round(annual_cost_without - annual_cost_with_motor))
            payback_period = (curtain_price / annual_savings_cost) if annual_savings_cost > 0 else None
            carbon_footprint = round((total_energy_without - annual_energy_with_motor) * EMISSION_FACTOR, 1)
            result = {
                "total_savings": int(round(sum(monthly_savings))),
                "energy_without": energy_without,
                "energy_with": energy_with,
                "motor_energy": motor_energy_list,
                "monthly_carbon_savings": monthly_carbon_savings,
                "months": months,
                "monthly_savings": monthly_savings,
                "monthly_operating_hours": effective_monthly_hours,
                "annual_energy_without": total_energy_without,
                "annual_cost_without": f"{annual_cost_without} EUR",
                "annual_energy_with": total_energy_with,
                "annual_cost_with": f"{annual_cost_with} EUR",
                "annual_motor_energy": annual_motor_energy,
                "annual_cost_motor": f"{annual_cost_motor} EUR",
                "annual_energy_with_motor": annual_energy_with_motor,
                "annual_cost_with_motor": f"{annual_cost_with_motor} EUR",
                "annual_savings_energy": annual_savings_energy,
                "annual_savings_cost": f"{annual_savings_cost} EUR",
                "payback_period": payback_period,
                "carbon_footprint": f"{carbon_footprint} kg CO₂/year"
            }
            chart_data = json.dumps({
                "months": months,
                "without": energy_without,
                "with": [energy_with[i] + motor_energy_list[i] for i in range(12)]
            })
            payback_chart_data = json.dumps({
                "years": list(range(0, 8)),  # ograniczenie do 7 lat (0-7)
                "without": [annual_cost_without * y for y in range(0, 8)],
                "with": [1100 + (annual_cost_with_motor * y) for y in range(0, 8)],
                "payback": payback_period
            })
        else:
            result = {
                "total_savings": "Brak danych",
                "energy_without": "Brak danych",
                "energy_with": "Brak danych",
                "motor_energy": "Brak danych",
                "monthly_carbon_savings": "Brak danych",
                "months": months,
                "monthly_savings": "Brak danych",
                "monthly_operating_hours": effective_monthly_hours,
                "annual_energy_without": "Brak danych",
                "annual_cost_without": "Brak danych",
                "annual_energy_with": "Brak danych",
                "annual_cost_with": "Brak danych",
                "annual_motor_energy": "Brak danych",
                "annual_cost_motor": "Brak danych",
                "annual_energy_with_motor": "Brak danych",
                "annual_cost_with_motor": "Brak danych",
                "annual_savings_energy": "Brak danych",
                "annual_savings_cost": "Brak danych",
                "payback_period": "Brak danych",
                "carbon_footprint": "Brak danych"
            }
            chart_data = json.dumps({
                "months": months,
                "without": [],
                "with": []
            })
            payback_chart_data = json.dumps({
                "years": [],
                "without": [],
                "with": [],
                "payback": "Brak danych"
            })

        result["monthly_wind"] = monthly_avg_wind
        result["operating_wind"] = operating_avg_wind

    return render_template("index.html", result=result, chart_data=chart_data,
                           payback_chart_data=payback_chart_data, weekly_chart_data=weekly_chart_data,
                           weekly_wind_chart_data=weekly_wind_chart_data,
                           temp_table=temp_table, chosen_station=chosen_station,
                           version=APP_VERSION, language=selected_language,
                           languages=languages, currencies=currencies)

@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    report_data = request.form.to_dict()
    rendered = render_template("pdf_report.html", data=report_data)
    pdf = pdfkit.from_string(rendered, False)
    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = "attachment; filename=raport.pdf"
    return response

if __name__ == "__main__":
    app.run(debug=True)
