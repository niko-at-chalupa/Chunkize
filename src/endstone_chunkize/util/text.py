from endstone import ColorFormat

PREFIX = f"{ColorFormat.GOLD}[Chunkize]{ColorFormat.RESET} "


def formatNumber(value):
    return f"{value:,}"


def formatDuration(seconds):
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
