"""Smart club matching algorithm: scores every club against a student's
selected categories, major, and time-commitment preference."""

MAJOR_KEYWORDS = {
    "Computer Science": ["computer", "software", "coding", "programming", "tech", "cs", "algorithm", "ai", "data", "cyber"],
    "Engineering": ["engineer", "technical", "robotics", "design", "build", "mechanical", "electrical"],
    "Business": ["business", "entrepreneur", "finance", "marketing", "consulting", "management"],
    "Pre-Med": ["medicine", "medical", "health", "pre-med", "premed", "clinical", "hospital", "dental"],
    "Biology": ["bio", "science", "research", "lab", "ecology", "cell", "molecular"],
    "Psychology": ["psych", "mental", "cognitive", "behavior", "counseling", "wellness"],
    "Art": ["art", "design", "creative", "visual", "music", "theater", "dance", "film"],
    "Communications": ["media", "journalism", "communication", "broadcasting", "writing"],
    "Economics": ["economic", "finance", "market", "business"],
    "Political Science": ["political", "policy", "government", "law", "justice"],
}

COMMITMENT_KEYWORDS = {
    "low": ["casual", "flexible", "open", "welcome"],
    "medium": ["weekly", "regular", "meeting"],
    "high": ["competitive", "team", "championship"],
}

MAJORS = list(MAJOR_KEYWORDS.keys()) + ["Other"]


def smart_match_clubs(clubs, categories, major="", time_commitment=""):
    """clubs: list of Club model instances. Returns a list of dicts sorted by score desc."""
    matches = []

    if not categories and not major:
        for club in clubs:
            matches.append({"club": club, "score": 50, "reasons": ["Browse all UW clubs"], "badge": None})
        return matches

    for club in clubs:
        score = 0
        reasons = []
        club_text = f"{club.name} {club.description}".lower()

        if categories and club.category in categories:
            score += 50
            reasons.append(f"{club.category} club")

        if major and major in MAJOR_KEYWORDS:
            for keyword in MAJOR_KEYWORDS[major]:
                if keyword in club_text:
                    score += 40
                    reasons.append(f"Great for {major} students")
                    break

        if time_commitment:
            for keyword in COMMITMENT_KEYWORDS.get(time_commitment, []):
                if keyword in club_text:
                    score += 10
                    break

        badge = None
        if score >= 80:
            badge = "perfect"
        elif score >= 60:
            badge = "great"
        elif score >= 40:
            badge = "good"

        if score > 0:
            matches.append({
                "club": club,
                "score": min(score, 100),
                "reasons": reasons or ["Matches your preferences"],
                "badge": badge,
            })

    matches.sort(key=lambda m: m["score"], reverse=True)

    if not matches and categories:
        for club in clubs:
            if club.category in categories:
                matches.append({"club": club, "score": 50, "reasons": [f"{club.category} club"], "badge": "good"})

    return matches
