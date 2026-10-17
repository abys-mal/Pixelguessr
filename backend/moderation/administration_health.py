"""Bounded read probes, without infrastructure details or raw exception output."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError

from django.conf import settings
from django.db import close_old_connections, connections

POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="health")


def database():
    close_old_connections()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            return "Healthy" if cursor.fetchone()[0] == 1 else "Degraded"
    finally:
        connections["default"].close()


def private_storage():
    from library.models import ImageSubmission

    close_old_connections()
    try:
        image = ImageSubmission.objects.exclude(image_file="").order_by("pk").first()
        if not image:
            return "Not Configured"
        with image.image_file.storage.open(image.image_file.name, "rb") as file:
            return "Healthy" if file.read(32) else "Degraded"
    finally:
        connections["default"].close()


def redis():
    location = settings.CACHES["default"].get("LOCATION")
    if "redis" not in settings.CACHES["default"]["BACKEND"].lower():
        return "Not Configured"
    from redis import Redis

    with Redis.from_url(location, socket_timeout=1, socket_connect_timeout=1) as client:
        return "Healthy" if client.ping() else "Degraded"


def health():
    probes = {
        name: POOL.submit(check)
        for name, check in [
            ("Database", database),
            ("Redis", redis),
            ("Private image storage (read)", private_storage),
        ]
    }
    result = []
    for name, future in probes.items():
        try:
            state = future.result(timeout=1.5)
        except (Exception, TimeoutError):
            state = "Unavailable"
            future.cancel()
        result.append({"name": name, "state": state})
    return result + [
        {"name": "Backend application", "state": "Healthy"},
        {"name": "Recent application error collection", "state": "Not Configured"},
    ]
