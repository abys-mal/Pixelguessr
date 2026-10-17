def honorary_title(user):
    if not user:
        return None
    title = getattr(user, "verified_title", None)
    return (
        title.title
        if title and not title.revoked_at and title.title in {"pro", "master", "legend"}
        else None
    )
