import argparse
from models import Preferences
from agent import TravelAgent


def main():
    parser = argparse.ArgumentParser(description="Travel Planner Agent")
    parser.add_argument("--city", type=str, required=False, help="Optional city to visit")
    parser.add_argument(
        "--budget", type=float, required=True, help="Total budget in USD"
    )
    parser.add_argument("--days", type=int, required=True, help="Number of days")
    parser.add_argument(
        "--interests",
        type=str,
        nargs="+",
        default=[],
        help="List of interests (e.g. Art Food)",
    )
    parser.add_argument("--vibe", type=str, default=None, help="Travel vibe or aesthetic")
    parser.add_argument("--work-friendly", action="store_true", help="Prefer work-friendly stays and environments")

    args = parser.parse_args()

    prefs = Preferences(
        city=args.city,
        budget=args.budget,
        days=args.days,
        interests=args.interests,
        vibe=args.vibe,
        work_friendly=args.work_friendly,
    )

    destination = prefs.city or "a recommended destination"
    print(f"--- Planning trip to {destination} for {prefs.days} days with budget ${prefs.budget} ---")
    if prefs.vibe:
        print(f"Vibe: {prefs.vibe}")
    if prefs.work_friendly:
        print("Work-friendly filtering: enabled")
    print(f"Interests: {', '.join(prefs.interests)}")

    agent = TravelAgent()
    itinerary = agent.plan_trip(prefs)

    print("\n=== Final Itinerary ===")
    if itinerary.valid:
        print("Status: VALID")
        print(f"Total Cost: ${itinerary.total_cost}")
        print(f"Destination: {itinerary.city}")
        if itinerary.vibe_rationale:
            print(f"Why: {itinerary.vibe_rationale}")
        for day in itinerary.days:
            print(f"\nDay {day.day_number}:")
            for act in day.activities:
                print(f"  - {act.name} (${act.cost}) [{', '.join(act.tags)}]")
    else:
        print("Status: INVALID")
        print(f"Error: {itinerary.validation_error}")
        print(f"Current Cost: ${itinerary.total_cost}")


if __name__ == "__main__":
    main()
