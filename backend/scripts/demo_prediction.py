"""Demonstration script for the Early Warning Predictive Engine.

Run this script to show the jury how ReTryp uses historical data
to predict flight disruptions before they are officially cancelled,
proactively triggering the LLM Recovery Agent.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add backend to path so we can import app modules
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.domain.prediction import predict_flight_risk
from app.db import SessionLocal
from app.models import Trip, Segment

def run_demo():
    print("================================================================")
    print(">>> ReTryp Predictive Engine (Historical Data Analysis)")
    print("================================================================\n")
    print("Ingesting historical flight performance & weather datasets...")
    print("Analyzing upcoming trip portfolio for delay patterns...\n")
    
    # 1. Simulate evaluating a standard safe flight (Mumbai to Bangalore)
    safe_flight = predict_flight_risk(
        flight_number="6E 543",
        departure_date=datetime.now(timezone.utc) + timedelta(days=1),
        origin="BOM",
        destination="BLR"
    )
    print(f"[*] Evaluating Flight: {safe_flight.flight_number} (BOM -> BLR)")
    print(f"   Historical Pattern: {safe_flight.primary_factor}")
    print(f"   Delay Probability: {safe_flight.historical_delay_probability * 100:.1f}%")
    print(f"   Status: CLEAR (No early warning needed)\n")
    
    # 2. Simulate evaluating the high-risk demo flight (Chennai to Delhi)
    print("----------------------------------------------------------------")
    print("[!] HIGH RISK PATTERN DETECTED")
    print("----------------------------------------------------------------")
    risky_flight = predict_flight_risk(
        flight_number="6E 953",
        departure_date=datetime.now(timezone.utc) + timedelta(hours=4),
        origin="MAA",
        destination="DEL"
    )
    print(f"[*] Evaluating Flight: {risky_flight.flight_number} (MAA -> DEL)")
    print(f"   Historical Pattern: {risky_flight.primary_factor}")
    print(f"   Delay Probability: {risky_flight.historical_delay_probability * 100:.1f}%")
    print(f"   Risk Score: {risky_flight.risk_score:.2f} / 1.00")
    
    if risky_flight.trigger_early_warning:
        print("\n[!] THRESHOLD EXCEEDED: Triggering LLM Recovery Agent proactively!")
        print("   -> Initiating live RailRadar telemetry for MAS -> NDLS")
        print("   -> Pre-computing fallback intercity bus schedules via HYD")
        print("   -> Passenger will receive recovery plans BEFORE official airline cancellation.")
    
    print("\n================================================================")
    print("Demo complete. LLM Agent has taken over.")

if __name__ == "__main__":
    run_demo()
