import json
from datetime import datetime, timedelta

def generate_dates(start_date_str, end_date_str):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)
    return dates

dates = generate_dates("2026-10-01", "2026-10-31")

rail_data = {
    "fetched_at": "2026-10-03T12:00:00.000000+00:00",
    "feed_version": "v1.1",
    "publisher": "Indian Railways — curated from published timetables",
    "source_url": "https://enquiry.indianrail.gov.in",
    "valid_from": "2026-10-01",
    "valid_to": "2027-03-31",
    "timezone": "Asia/Kolkata",
    "currency": "INR",
    "fare_model": "curated_3ac",
    "services": [
        # Direct MAS -> NDLS
        {"origin": "MAS_RS", "destination": "NDLS", "service": "Rajdhani Express 12433/12434", "operator": "Indian Railways", "departure": "06:10:00", "arrival": "34:10:00", "duration_min": 1680, "dates": dates, "trip_id": "IR-12433-MAS-NDLS", "fare_minor": 320000},
        {"origin": "MAS_RS", "destination": "NDLS", "service": "GT Express 12615/12616", "operator": "Indian Railways", "departure": "18:45:00", "arrival": "51:45:00", "duration_min": 1980, "dates": dates, "trip_id": "IR-12615-MAS-NDLS", "fare_minor": 180000},
        {"origin": "MAS_RS", "destination": "NDLS", "service": "Tamil Nadu Express 12621/12622", "operator": "Indian Railways", "departure": "22:00:00", "arrival": "53:30:00", "duration_min": 1890, "dates": dates, "trip_id": "IR-12621-MAS-NDLS", "fare_minor": 280000},
        
        # MAS -> SC_RS (Secunderabad / Hyderabad)
        {"origin": "MAS_RS", "destination": "SC_RS", "service": "Charminar Express 12759/12760", "operator": "Indian Railways", "departure": "18:30:00", "arrival": "30:30:00", "duration_min": 720, "dates": dates, "trip_id": "IR-12759-MAS-SC", "fare_minor": 80000},
        {"origin": "MAS_RS", "destination": "SC_RS", "service": "Duronto Express 12269/12270", "operator": "Indian Railways", "departure": "22:10:00", "arrival": "32:00:00", "duration_min": 590, "dates": dates, "trip_id": "IR-12269-MAS-SC", "fare_minor": 150000},
        
        # SC_RS -> NDLS
        {"origin": "SC_RS", "destination": "NDLS", "service": "Telangana Express 12723/12724", "operator": "Indian Railways", "departure": "06:25:00", "arrival": "29:55:00", "duration_min": 1410, "dates": dates, "trip_id": "IR-12723-SC-NDLS", "fare_minor": 170000},
        {"origin": "SC_RS", "destination": "NDLS", "service": "Rajdhani Express 12437/12438", "operator": "Indian Railways", "departure": "06:55:00", "arrival": "27:55:00", "duration_min": 1260, "dates": dates, "trip_id": "IR-12437-SC-NDLS", "fare_minor": 280000},
        {"origin": "SC_RS", "destination": "NDLS", "service": "AP Sampark Kranti 12707", "operator": "Indian Railways", "departure": "09:00:00", "arrival": "34:30:00", "duration_min": 1530, "dates": dates, "trip_id": "IR-12707-SC-NDLS", "fare_minor": 190000},
        {"origin": "SC_RS", "destination": "NDLS", "service": "Dakshin Express 12721", "operator": "Indian Railways", "departure": "23:00:00", "arrival": "51:50:00", "duration_min": 1730, "dates": dates, "trip_id": "IR-12721-SC-NDLS", "fare_minor": 180000},
        
        # MAS -> SBC_RS (Bengaluru)
        {"origin": "MAS_RS", "destination": "SBC_RS", "service": "Shatabdi Express 12027/12028", "operator": "Indian Railways", "departure": "06:00:00", "arrival": "11:00:00", "duration_min": 300, "dates": dates, "trip_id": "IR-12027-MAS-SBC", "fare_minor": 110000},
        {"origin": "MAS_RS", "destination": "SBC_RS", "service": "Lalbagh Express 12607/12608", "operator": "Indian Railways", "departure": "06:40:00", "arrival": "11:40:00", "duration_min": 300, "dates": dates, "trip_id": "IR-12607-MAS-SBC", "fare_minor": 95000},
        {"origin": "MAS_RS", "destination": "SBC_RS", "service": "Brindavan Express 12639", "operator": "Indian Railways", "departure": "07:40:00", "arrival": "13:40:00", "duration_min": 360, "dates": dates, "trip_id": "IR-12639-MAS-SBC", "fare_minor": 70000},
        {"origin": "MAS_RS", "destination": "SBC_RS", "service": "Chennai Bengaluru Mail 12657", "operator": "Indian Railways", "departure": "22:50:00", "arrival": "28:30:00", "duration_min": 340, "dates": dates, "trip_id": "IR-12657-MAS-SBC", "fare_minor": 85000},
        
        # SBC_RS -> NDLS
        {"origin": "SBC_RS", "destination": "NDLS", "service": "Karnataka Express 12627", "operator": "Indian Railways", "departure": "19:20:00", "arrival": "57:30:00", "duration_min": 2290, "dates": dates, "trip_id": "IR-12627-SBC-NDLS", "fare_minor": 290000},
        {"origin": "SBC_RS", "destination": "NDLS", "service": "Duronto Express 12213/12214", "operator": "Indian Railways", "departure": "20:00:00", "arrival": "54:00:00", "duration_min": 2040, "dates": dates, "trip_id": "IR-12213-SBC-NDLS", "fare_minor": 300000},
        
        # Other corridors
        {"origin": "MMCT", "destination": "NDLS", "service": "Rajdhani Express 12951/12952", "operator": "Indian Railways", "departure": "16:35:00", "arrival": "32:35:00", "duration_min": 960, "dates": dates, "trip_id": "IR-12951-MMCT-NDLS", "fare_minor": 250000},
        {"origin": "HWH", "destination": "NDLS", "service": "Howrah Rajdhani 12301/12302", "operator": "Indian Railways", "departure": "16:50:00", "arrival": "33:50:00", "duration_min": 1020, "dates": dates, "trip_id": "IR-12301-HWH-NDLS", "fare_minor": 260000}
    ]
}

bus_data = {
    "fetched_at": "2026-10-03T12:00:00.000000+00:00",
    "feed_version": "v1.1",
    "publisher": "Curated from state transport corporation and private operator schedules",
    "source_url": "https://www.redbus.in",
    "valid_from": "2026-10-01",
    "valid_to": "2027-03-31",
    "timezone": "Asia/Kolkata",
    "currency": "INR",
    "fare_model": "published_fare",
    "transport_type": "bus",
    "services": [
        # MAS -> HYD
        {"origin": "MAS_BT", "destination": "HYD_BT", "operator": "APSRTC Super Luxury Express", "departure": "17:00:00", "arrival": "28:00:00", "duration_min": 660, "dates": dates, "trip_id": "BUS-APSRTC-SL1", "fare_minor": 95000},
        {"origin": "MAS_BT", "destination": "HYD_BT", "operator": "APSRTC Garuda Plus", "departure": "21:00:00", "arrival": "31:00:00", "duration_min": 600, "dates": dates, "trip_id": "BUS-APSRTC-1", "fare_minor": 120000},
        {"origin": "MAS_BT", "destination": "HYD_BT", "operator": "APSRTC Volvo Multi-Axle", "departure": "22:00:00", "arrival": "33:00:00", "duration_min": 660, "dates": dates, "trip_id": "BUS-APSRTC-2", "fare_minor": 100000},
        {"origin": "MAS_BT", "destination": "HYD_BT", "operator": "SRS Travels AC Sleeper", "departure": "20:00:00", "arrival": "31:00:00", "duration_min": 660, "dates": dates, "trip_id": "BUS-SRS-1", "fare_minor": 140000},
        
        # MAS -> BLR
        {"origin": "MAS_BT", "destination": "BLR_BT", "operator": "KSRTC Airavat Club Class", "departure": "14:00:00", "arrival": "20:00:00", "duration_min": 360, "dates": dates, "trip_id": "BUS-KSRTC-D1", "fare_minor": 90000},
        {"origin": "MAS_BT", "destination": "BLR_BT", "operator": "KSRTC Airavat Club Class", "departure": "22:30:00", "arrival": "28:30:00", "duration_min": 360, "dates": dates, "trip_id": "BUS-KSRTC-1", "fare_minor": 90000},
        {"origin": "MAS_BT", "destination": "BLR_BT", "operator": "TNSTC Ultra Deluxe", "departure": "23:00:00", "arrival": "30:00:00", "duration_min": 420, "dates": dates, "trip_id": "BUS-TNSTC-1", "fare_minor": 65000},
        
        # Other corridors
        {"origin": "BLR_BT", "destination": "HYD_BT", "operator": "KSRTC Airavat", "departure": "21:30:00", "arrival": "30:30:00", "duration_min": 540, "dates": dates, "trip_id": "BUS-KSRTC-2", "fare_minor": 85000},
        {"origin": "HYD_BT", "destination": "BLR_BT", "operator": "Orange Travels", "departure": "22:00:00", "arrival": "31:00:00", "duration_min": 540, "dates": dates, "trip_id": "BUS-ORANGE-1", "fare_minor": 95000},
        {"origin": "DEL_BT", "destination": "JP_RS", "operator": "UPSRTC AC Seater", "departure": "06:00:00", "arrival": "11:30:00", "duration_min": 330, "dates": dates, "trip_id": "BUS-UPSRTC-1", "fare_minor": 70000}
    ]
}

with open(r'c:\Users\Monish P\Downloads\ReTryp v1\ReTryp v1\project\backend\app\data\indian_rail_services.json', 'w', encoding='utf-8') as f:
    json.dump(rail_data, f, ensure_ascii=False, indent=2)

with open(r'c:\Users\Monish P\Downloads\ReTryp v1\ReTryp v1\project\backend\app\data\indian_bus_services.json', 'w', encoding='utf-8') as f:
    json.dump(bus_data, f, ensure_ascii=False, indent=2)

print("Data regenerated successfully.")
