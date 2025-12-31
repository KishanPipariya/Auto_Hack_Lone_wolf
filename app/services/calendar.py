from ics import Calendar, Event
from models import Itinerary
from datetime import datetime, timedelta
import pytz


def generate_ics(itinerary: Itinerary, start_date_str: str | None = None) -> bytes:
    """
    Generates an iCalendar (.ics) file content from an itinerary.
    If start_date_str is None, defaults to tomorrow.
    """
    # 1. Determine Start Date
    # 1. Determine Start Date
    start_date = None
    if start_date_str:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                start_date = datetime.strptime(start_date_str, fmt).date()
                break
            except ValueError:
                continue

    if not start_date:
        # Default to tomorrow if parsing fails or no date provided
        start_date = (datetime.now() + timedelta(days=1)).date()

    cal = Calendar()

    # 2. Iterate through days
    for day in itinerary.days:
        current_day_date = start_date + timedelta(days=day.day_number - 1)

        # Create an All-Day Summary Event
        summary_event = Event()
        summary_event.name = f"Day {day.day_number}: {itinerary.city} Trip"
        summary_event.begin = datetime.combine(current_day_date, datetime.min.time())
        summary_event.make_all_day()
        summary_event.description = f"Total Cost for Day: ${sum(a.cost for a in day.activities if isinstance(a.cost, (int, float)))}"
        cal.events.add(summary_event)

        # 3. Create Timed Events for Activities
        # Start at 09:00 AM local time (naive)
        current_time = datetime.combine(
            current_day_date, datetime.strptime("09:00", "%H:%M").time()
        )

        for activity in day.activities:
            event = Event()
            event.name = f"{activity.name} ({itinerary.city})"
            event.description = f"{activity.description}\n\nCost: ${activity.cost}\nTags: {', '.join(activity.tags)}"
            if activity.image_url:
                event.description += f"\nImage: {activity.image_url}"

            event.begin = current_time

            # Duration logic
            duration_hours = (
                activity.duration_hours
                if isinstance(activity.duration_hours, (int, float))
                else 1.0
            )
            # Cap crazy durations
            if duration_hours > 8:
                duration_hours = 8
            if duration_hours < 0.5:
                duration_hours = 0.5

            event.duration = timedelta(hours=duration_hours)

            cal.events.add(event)

            # Advance time for next activity + 30 min travel buffer
            current_time += timedelta(hours=duration_hours) + timedelta(minutes=30)

    return cal.serialize().encode("utf-8")
