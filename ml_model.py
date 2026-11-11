# Transparent demonstration baseline. Replace with a trained model using a
# documented historical dataset before presenting it as a validated forecast.
def predict_demo(x):
    pm25=x["pm25"]; pm10=x["pm10"]; no2=x["no2"]; o3=x["o3"]
    # A simple weighted indicator, not an official AQI calculation.
    estimate = 0.55*pm25 + 0.25*pm10 + 0.10*no2 + 0.10*o3
    return {"aqi": max(0, min(500, round(estimate)))}
