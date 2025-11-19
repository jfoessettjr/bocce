import os
from datetime import date

from flask import Flask, render_template, request, redirect, url_for
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Date,
    Time,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# If DATABASE_URL is not set, default to local SQLite (useful for quick testing)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bocce.db")

# Required for some Postgres URLs that start with postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False, future=True)

SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False)
)

Base = declarative_base()

app = Flask(__name__)


# -----------------------
# Database Models
# -----------------------

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    home_matches = relationship(
        "Match", back_populates="home_team", foreign_keys="Match.home_team_id"
    )
    away_matches = relationship(
        "Match", back_populates="away_team", foreign_keys="Match.away_team_id"
    )

    def __repr__(self):
        return f"<Team {self.name}>"


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True)
    week = Column(Integer, nullable=False)
    match_date = Column(Date, nullable=False)
    match_time = Column(String)  # keep as string for simplicity
    court = Column(String)

    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)

    home_score = Column(Integer)
    away_score = Column(Integer)

    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matches")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matches")

    def __repr__(self):
        return f"<Match week={self.week} {self.home_team} vs {self.away_team}>"


# -----------------------
# App / DB lifecycle
# -----------------------

def init_db():
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)


@app.teardown_appcontext
def shutdown_session(exception=None):
    SessionLocal.remove()


# Call this when the app starts (Flask 3.x-safe)
with app.app_context():
    init_db()


# -----------------------
# Helper functions
# -----------------------

def get_or_create_team(session, team_name: str) -> Team:
    name = team_name.strip()
    team = session.query(Team).filter_by(name=name).one_or_none()
    if team is None:
        team = Team(name=name)
        session.add(team)
        session.commit()
        session.refresh(team)
    return team


def compute_standings(session):
    teams = session.query(Team).all()
    standings = []

    for team in teams:
        games_won = 0
        games_lost = 0

        # All series (matches) where this team participated
        matches = (
            session.query(Match)
            .filter(
                (Match.home_team_id == team.id) |
                (Match.away_team_id == team.id)
            )
            .all()
        )

        for m in matches:
            # Skip if no scores yet
            if m.home_score is None or m.away_score is None:
                continue

            if m.home_team_id == team.id:
                # Team is home
                games_won += m.home_score or 0
                games_lost += m.away_score or 0
            else:
                # Team is away
                games_won += m.away_score or 0
                games_lost += m.home_score or 0

        games_played = games_won + games_lost
        win_pct = (games_won / games_played) if games_played > 0 else 0

        standings.append({
            "team": team,
            "games_won": games_won,
            "games_lost": games_lost,
            "games_played": games_played,
            "win_pct": win_pct,
        })

    # Sort by win %, then by total games won
    standings.sort(key=lambda r: (-r["win_pct"], -r["games_won"]))
    return standings


def get_latest_week(session):
    latest_week = session.query(Match.week).order_by(Match.week.desc()).first()
    return latest_week[0] if latest_week else 0


# -----------------------
# Routes
# -----------------------

@app.route("/")
def index():
    return redirect(url_for("standings"))


@app.route("/standings")
def standings():
    session = SessionLocal()
    try:
        standings_data = compute_standings(session)
        max_week = get_latest_week(session)
        return render_template(
            "standings.html",
            standings=standings_data,
            max_week=max_week
        )
    finally:
        session.close()


@app.route("/matches/week/<int:week>")
def week_matches(week):
    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .filter(Match.week == week)
            .order_by(Match.match_date, Match.match_time)
            .all()
        )
        return render_template("week_matches.html", matches=matches, week=week)
    finally:
        session.close()
        
@app.route("/team/<int:team_id>")
def team_detail(team_id):
    session = SessionLocal()
    try:
        # Get the team or 404 if it doesn't exist
        team = session.get(Team, team_id)
        if team is None:
            abort(404)

        # All matches involving this team
        matches = (
            session.query(Match)
            .filter(
                (Match.home_team_id == team_id) |
                (Match.away_team_id == team_id)
            )
            .order_by(Match.week, Match.match_date, Match.match_time)
            .all()
        )

        # Games-based record
        games_won = 0
        games_lost = 0

        for m in matches:
            if m.home_score is None or m.away_score is None:
                continue

            if m.home_team_id == team_id:
                games_won += m.home_score or 0
                games_lost += m.away_score or 0
            else:
                games_won += m.away_score or 0
                games_lost += m.home_score or 0

        games_played = games_won + games_lost

        return render_template(
            "team_detail.html",
            team=team,
            matches=matches,
            wins=games_won,
            losses=games_lost,
            ties=None,
            games_played=games_played,
        )
    finally:
        session.close()


@app.route("/schedule")
def schedule():
    session = SessionLocal()
    try:
        matches = (
            session.query(Match)
            .order_by(Match.week, Match.match_date, Match.match_time)
            .all()
        )

        # Group matches by week: {week_number: [Match, Match, ...]}
        weeks = {}
        for m in matches:
            weeks.setdefault(m.week, []).append(m)

        # Sort by week number
        ordered_weeks = sorted(weeks.items(), key=lambda x: x[0])

        return render_template("schedule.html", weeks=ordered_weeks)
    finally:
        session.close()


@app.route("/match/new", methods=["GET", "POST"])
def add_match():
    session = SessionLocal()

    try:
        if request.method == "POST":
            week = int(request.form["week"])
            match_date_str = request.form["match_date"]  # 'YYYY-MM-DD'
            match_time = request.form["match_time"]
            court = request.form["court"]
            home_team_name = request.form["home_team"]
            away_team_name = request.form["away_team"]

            home_score_raw = request.form.get("home_score")
            away_score_raw = request.form.get("away_score")

            home_score = int(home_score_raw) if home_score_raw else None
            away_score = int(away_score_raw) if away_score_raw else None

            # Convert date string to date object
            year, month, day = map(int, match_date_str.split("-"))
            match_date = date(year, month, day)

            # Ensure teams exist or create them
            home_team = get_or_create_team(session, home_team_name)
            away_team = get_or_create_team(session, away_team_name)

            match = Match(
                week=week,
                match_date=match_date,
                match_time=match_time,
                court=court,
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                home_score=home_score,
                away_score=away_score,
            )

            session.add(match)
            session.commit()

            return redirect(url_for("standings"))

        # GET: show form
        teams = session.query(Team).order_by(Team.name.asc()).all()
        return render_template("add_match.html", teams=teams)
    finally:
        session.close()


if __name__ == "__main__":
    # For Codespaces, often host='0.0.0.0'
    app.run(debug=True, host="0.0.0.0", port=5000)