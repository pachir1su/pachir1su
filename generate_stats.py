import os
import math
import requests
from datetime import datetime

# GitHub API configuration
TOKEN = os.environ['GITHUB_TOKEN']
USERNAME = 'pachir1su'
CURRENT_YEAR = datetime.now().year

HEADERS = {
    'Authorization': f'bearer {TOKEN}',
    'Content-Type': 'application/json',
}

# GraphQL query to fetch user statistics
QUERY = '''
query($login: String!) {
  user(login: $login) {
    name
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes { stargazers { totalCount } }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestReviewContributions
    }
    pullRequests { totalCount }
    issues { totalCount }
  }
}
'''

def fetch_stats():
    """Fetch user stats from GitHub GraphQL API."""
    resp = requests.post(
        'https://api.github.com/graphql',
        headers=HEADERS,
        json={'query': QUERY, 'variables': {'login': USERNAME}},
        timeout=30,
    )
    resp.raise_for_status()
    user = resp.json()['data']['user']

    return {
        'name': user['name'] or USERNAME,
        'stars':    sum(r['stargazers']['totalCount'] for r in user['repositories']['nodes']),
        'commits':  user['contributionsCollection']['totalCommitContributions'],
        'reviews':  user['contributionsCollection']['totalPullRequestReviewContributions'],
        'prs':      user['pullRequests']['totalCount'],
        'issues':   user['issues']['totalCount'],
        'followers': user['followers']['totalCount'],
    }

def _normalcdf(mean, sigma, x):
    """Normal CDF via error function."""
    z = (x - mean) / (sigma * math.sqrt(2))
    return 0.5 * (1 + math.erf(z))

def calculate_rank(stats):
    """Calculate rank using the same algorithm as github-readme-stats."""
    metrics = [
        (stats['commits'],  250, 2),
        (stats['prs'],       50, 3),
        (stats['issues'],    25, 1),
        (stats['reviews'],    2, 1),
        (stats['stars'],     50, 4),
        (stats['followers'], 10, 1),
    ]
    total_weight = sum(w for _, _, w in metrics)
    score = sum(
        w * _normalcdf(median, median, value)
        for value, median, w in metrics
    ) / total_weight

    percentile = (1 - score) * 100

    if percentile < 1:    return 'S'
    if percentile < 12.5: return 'A+'
    if percentile < 25:   return 'A'
    if percentile < 37.5: return 'A-'
    if percentile < 50:   return 'B+'
    if percentile < 62.5: return 'B'
    if percentile < 75:   return 'B-'
    if percentile < 87.5: return 'C+'
    return 'C'

def generate_svg(stats):
    """Generate a tokyonight-themed GitHub Stats SVG."""
    rank = calculate_rank(stats)

    # Map rank to ring fill (circumference ~= 251 for r=40)
    fill_map = {'S': 246, 'A+': 220, 'A': 188, 'A-': 157,
                'B+': 125, 'B': 94, 'B-': 63, 'C+': 32, 'C': 16}
    dash = fill_map.get(rank, 125)
    rank_color = '#38bdae' if rank in ('S', 'A+', 'A', 'A-') else '#a9fef7'

    name = stats['name'].replace('&', '&amp;').replace('<', '&lt;')

    svg = f'''<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" rx="4.5" height="99%" stroke="#e4e2e2" stroke-opacity="0.2" fill="#1a1b27" width="494"/>
  <text x="25" y="35" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="18" font-weight="600" fill="#38bdae">{name}&apos;s GitHub Stats</text>

  <text x="25"  y="75"  font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" fill="#a9fef7">&#9733; Total Stars Earned:</text>
  <text x="220" y="75"  font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" font-weight="700" fill="#e4e2e2">{stats["stars"]}</text>

  <text x="25"  y="105" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" fill="#a9fef7">&#8635; Total Commits ({CURRENT_YEAR}):</text>
  <text x="220" y="105" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" font-weight="700" fill="#e4e2e2">{stats["commits"]}</text>

  <text x="25"  y="135" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" fill="#a9fef7">&#10145; Total PRs:</text>
  <text x="220" y="135" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" font-weight="700" fill="#e4e2e2">{stats["prs"]}</text>

  <text x="25"  y="165" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" fill="#a9fef7">&#9679; Total Issues:</text>
  <text x="220" y="165" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="14" font-weight="700" fill="#e4e2e2">{stats["issues"]}</text>

  <g transform="translate(390,97)">
    <circle cx="0" cy="0" r="40" fill="none" stroke="#e4e2e2" stroke-opacity="0.2" stroke-width="6"/>
    <circle cx="0" cy="0" r="40" fill="none" stroke="{rank_color}" stroke-width="6"
      stroke-dasharray="{dash} 251" stroke-linecap="round" transform="rotate(-90)"/>
    <text x="0" y="8"  text-anchor="middle" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="22" font-weight="800" fill="{rank_color}">{rank}</text>
    <text x="0" y="26" text-anchor="middle" font-family="Segoe UI,Ubuntu,Sans-Serif" font-size="11" fill="#7480a1">Grade</text>
  </g>
</svg>'''

    with open('github-stats.svg', 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f'Generated github-stats.svg — Rank: {rank}')

if __name__ == '__main__':
    stats = fetch_stats()
    generate_svg(stats)
