"""How the platform identifies itself when it fetches someone else's resource.

arXiv answers 503 to anonymous API traffic under load, which reaches a submitter
as "arXiv is unavailable" — true, but ours to fix rather than theirs.
"""

HEADERS = {"User-Agent": "koala.science/1.0 (+https://koala.science)"}
