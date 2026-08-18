import json
import math
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

USERNAME = "pachir1su"
HISTORY_PATH = Path("rank-history.json")
TIMEZONE = ZoneInfo("Asia/Seoul")
RANKS = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
RANK_INDEX = {rank: index for index, rank in enumerate(RANKS)}

TOKEN = os.environ["GITHUB_TOKEN"]
HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Content-Type": "application/json",
}

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, first: 100) {
      nodes {
        isFork
        stargazers { totalCount }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
    }
    pullRequests { totalCount }
    issues { totalCount }
  }
}
"""


def fetchStats():
    """Fetch the inputs used by the profile card and upstream rank formula."""
    response = requests.post(
        "https://api.github.com/graphql",
        headers=HEADERS,
        json={"query": QUERY, "variables": {"login": USERNAME}},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {payload['errors']}")

    user = payload["data"]["user"]
    repositories = user["repositories"]["nodes"]

    profileStars = sum(
        repository["stargazers"]["totalCount"]
        for repository in repositories
        if not repository["isFork"]
    )
    upstreamStars = sum(
        repository["stargazers"]["totalCount"] for repository in repositories
    )

    return {
        "commits": user["contributionsCollection"]["totalCommitContributions"],
        "reviews": user["contributionsCollection"][
            "totalPullRequestReviewContributions"
        ],
        "pull_requests": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "profile_stars": profileStars,
        "upstream_stars": upstreamStars,
    }


def normalCdf(mean, sigma, value):
    z = (value - mean) / (sigma * math.sqrt(2))
    return 0.5 * (1 + math.erf(z))


def calculateProfileRank(stats):
    """Mirror the normal-CDF ranking currently used by generate_stats.py."""
    metrics = [
        (stats["commits"], 250, 2),
        (stats["pull_requests"], 50, 3),
        (stats["issues"], 25, 1),
        (stats["reviews"], 2, 1),
        (stats["profile_stars"], 50, 4),
        (stats["followers"], 10, 1),
    ]
    score = sum(
        weight * normalCdf(median, median, value)
        for value, median, weight in metrics
    ) / 12
    percentile = (1 - score) * 100

    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    for threshold, rank in zip(thresholds, RANKS):
        if percentile < threshold:
            return rank, percentile
    return "C", percentile


def exponentialCdf(value):
    return 1 - 2 ** (-value)


def logNormalCdf(value):
    return value / (1 + value)


def calculateUpstreamRank(stats):
    """Mirror the current github-readme-stats calculateRank.js formula."""
    weightedScore = (
        2 * exponentialCdf(stats["commits"] / 250)
        + 3 * exponentialCdf(stats["pull_requests"] / 50)
        + exponentialCdf(stats["issues"] / 25)
        + exponentialCdf(stats["reviews"] / 2)
        + 4 * logNormalCdf(stats["upstream_stars"] / 50)
        + logNormalCdf(stats["followers"] / 10)
    ) / 12
    percentile = (1 - weightedScore) * 100

    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    for threshold, rank in zip(thresholds, RANKS):
        if percentile <= threshold:
            return rank, percentile
    return "C", percentile


def rankStats(stats, starsKey):
    return {
        "stars": stats[starsKey],
        "commits": stats["commits"],
        "pull_requests": stats["pull_requests"],
        "issues": stats["issues"],
        "reviews": stats["reviews"],
        "followers": stats["followers"],
    }


def buildObservation(stats):
    profileRank, profilePercentile = calculateProfileRank(stats)
    upstreamRank, upstreamPercentile = calculateUpstreamRank(stats)

    return {
        "observed_at": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
        "profile_card": {
            "rank": profileRank,
            "percentile": round(profilePercentile, 6),
            "stats": rankStats(stats, "profile_stars"),
        },
        "github_readme_stats": {
            "rank": upstreamRank,
            "percentile": round(upstreamPercentile, 6),
            "stats": rankStats(stats, "upstream_stars"),
        },
    }


def loadHistory():
    with HISTORY_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def saveHistory(history):
    with HISTORY_PATH.open("w", encoding="utf-8") as file:
        json.dump(history, file, ensure_ascii=False, indent=2)
        file.write("\n")


def buildRankChange(source, previous, current):
    previousRank = previous[source]["rank"]
    currentRank = current[source]["rank"]
    direction = (
        "promotion"
        if RANK_INDEX[currentRank] < RANK_INDEX[previousRank]
        else "regression"
    )

    return {
        "source": source,
        "direction": direction,
        "from": previousRank,
        "to": currentRank,
        "detected_at": current["observed_at"],
        "previous_recorded_at": previous["observed_at"],
        "previous_percentile": previous[source]["percentile"],
        "current_percentile": current[source]["percentile"],
        "stats": current[source]["stats"],
    }


def main():
    stats = fetchStats()
    observation = buildObservation(stats)
    history = loadHistory()
    previous = history.get("current")

    if previous is None:
        history["current"] = observation
        saveHistory(history)
        print(
            "Initialized rank history: "
            f"profile={observation['profile_card']['rank']}, "
            f"upstream={observation['github_readme_stats']['rank']}"
        )
        return

    changes = []
    for source in ("profile_card", "github_readme_stats"):
        if previous[source]["rank"] != observation[source]["rank"]:
            changes.append(buildRankChange(source, previous, observation))

    if not changes:
        print(
            "No rank change: "
            f"profile={observation['profile_card']['rank']}, "
            f"upstream={observation['github_readme_stats']['rank']}"
        )
        return

    history["rank_changes"].extend(changes)
    history["current"] = observation
    saveHistory(history)

    for change in changes:
        print(
            f"{change['source']}: {change['from']} -> {change['to']} "
            f"({change['direction']})"
        )


if __name__ == "__main__":
    main()
