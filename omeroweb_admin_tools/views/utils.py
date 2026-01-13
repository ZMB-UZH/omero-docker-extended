def current_username(request, conn):
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None
