from flask import Blueprint, Response, current_app, jsonify, request

from app.business import DomainIssue
from app.compensation.detect import is_compensation
from app.compensation.pipeline import build as build_compensation
from app.compensation.service import identifiers
from app.evidence.render import artifact
from app.inputs import read_input
from app.modules.pipeline import run
from app.review.service import execute, review

api = Blueprint("api", __name__, url_prefix="/api")
STAGES = {"intake": 1, "prepare": 2, "calculate": 3, "policy": 4, "balance": 5}


def preview_report(store, data, stage):
    if not is_compensation(data):
        return run(data, STAGES[stage])
    return build_compensation(data, STAGES[stage], store.ledger(identifiers(data)))


@api.post("/stages/<stage>")
def preview(stage):
    if stage not in STAGES:
        raise DomainIssue("STAGE_UNKNOWN")
    store = current_app.extensions["runs"]
    return jsonify(preview_report(store, read_input(), stage))


@api.route("/runs", methods=["GET", "POST"])
def runs():
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(items=store.list())
    return jsonify(execute(store, read_input()))


@api.route("/runs/<run_id>", methods=["GET", "PATCH"])
def batch(run_id):
    store = current_app.extensions["runs"]
    if request.method == "GET":
        return jsonify(store.load(run_id))
    return jsonify(review(store, run_id, request.get_json(silent=True)))


@api.get("/runs/<run_id>/evidence")
def export(run_id):
    report = current_app.extensions["runs"].load(run_id)
    return Response(
        artifact(report),
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="review-{report["id"][:12]}.json"',
            "Cache-Control": "no-store",
        },
    )


@api.get("/ledger")
def ledger():
    entries = current_app.extensions["runs"].ledger_entries()
    return jsonify(
        items=entries,
        offset_cents=sum(row["offset_cents"] for row in entries),
        settled_cents=sum(row["settled_cents"] for row in entries),
    )
