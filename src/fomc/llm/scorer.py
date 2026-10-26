"""Claude scoring engine: synchronous pilot calls, Message Batches for bulk runs.

Records are written one JSON file per job under
data/llm/<model>/<rubric_version>/<mode>/<key>.json and contain the full
response, message and request IDs, usage, the parsed output and a
verification of every quoted passage against the source text. A job whose
record already exists with the same input hash is never sent again, so reruns
cost nothing and repeated runs (for stability tests) need an explicit run tag.

The API key is read from the environment (ANTHROPIC_API_KEY or another
credential source the SDK supports) and is never printed or written.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ..config import INTERIM, LLM_DIR, settings
from . import provider, rubric

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canon(text: str) -> str:
    """Comparison form for verbatim checks: unify quotes, dashes, case and whitespace."""
    table = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
    text = text.translate(table).replace("--", "-")
    return " ".join(text.lower().split())


_CANON = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def canon_map(text: str) -> tuple[str, list[int]]:
    """canon(text) and, for every character of it, the index of the source character it came from."""
    chars, where, i, space = [], [], 0, True
    while i < len(text):
        ch = text[i].translate(_CANON)
        step = 2 if ch == "-" and i + 1 < len(text) and text[i + 1].translate(_CANON) == "-" else 1
        if ch.isspace():
            if not space:
                chars.append(" ")
                where.append(i)
            space = True
        else:
            chars.append(ch.lower())
            where.append(i)
            space = False
        i += step
    if chars and chars[-1] == " ":
        chars.pop()
        where.pop()
    return "".join(chars), where


def verify_quotes(quotes: list[str], source: str) -> dict:
    """Is every quote verbatim in the source (typography and case aside)? Verified quotes come back as
    evidence spans: character offsets [start, end) into the source text."""
    src, where = canon_map(source)
    checked, spans = [], []
    for q in quotes:
        if not q.strip():
            continue
        probe = canon(q).strip(" .,;:\"'")
        at = src.find(probe) if probe else -1
        checked.append((q, at >= 0))
        if at >= 0:
            spans.append({"quote": q, "start": where[at], "end": where[at + len(probe) - 1] + 1})
    ok = sum(v for _, v in checked)
    return {
        "n": len(checked),
        "verified": ok,
        "share": ok / len(checked) if checked else None,
        "unverified": [q for q, v in checked if not v],
        "spans": spans,
    }


@dataclass
class Job:
    mode: str
    key: str
    system: str
    message: str
    schema: dict
    meta: dict = field(default_factory=dict)

    @property
    def input_sha(self) -> str:
        return sha(self.system + "\x00" + self.message + "\x00" + json.dumps(self.schema, sort_keys=True))


class Scorer:
    def __init__(
        self,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int | None = None,
        run_tag: str = "",
        client=None,
    ):
        cfg = settings()["llm"]
        self.model = model or cfg["model"]
        self.effort = effort or cfg["effort"]
        self.max_tokens = max_tokens or cfg["max_tokens"]
        self.run_tag = run_tag  # "" for the main run; "r2", "r3" for repeats
        self.client = client or provider.get_client()

    # ------------------------------------------------------------------ paths
    def root(self, mode: str) -> Path:
        return LLM_DIR / self.model / rubric.RUBRIC_VERSION / (mode + (f"_{self.run_tag}" if self.run_tag else ""))

    def path(self, job: Job) -> Path:
        return self.root(job.mode) / f"{job.key}.json"

    def done(self, job: Job) -> bool:
        p = self.path(job)
        if not p.exists():
            return False
        rec = json.loads(p.read_text())
        return rec.get("input_sha256") == job.input_sha and rec.get("status") == "ok"

    # --------------------------------------------------------------- requests
    def params(self, job: Job) -> dict:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": job.schema}},
            "system": [{"type": "text", "text": job.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": job.message}],
        }

    def _record(self, job: Job, msg, *, batch_id: str | None = None, request_id: str | None = None) -> dict:
        text = next((b.text for b in msg.content if b.type == "text"), "")
        rec = {
            "key": job.key,
            "mode": job.mode,
            "meta": job.meta,
            "run_tag": self.run_tag,
            "model_requested": self.model,
            "model_served": msg.model,
            "effort": self.effort,
            "rubric_version": rubric.RUBRIC_VERSION,
            "input_sha256": job.input_sha,
            "message_id": msg.id,
            "request_id": request_id,
            "batch_id": batch_id,
            "stop_reason": msg.stop_reason,
            "usage": msg.usage.to_dict(),
            "fallback_used": any(getattr(b, "type", "") == "fallback" for b in msg.content),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "raw_text": text,
            "parsed": None,
            "status": "ok",
            "error": None,
        }
        if msg.stop_reason == "refusal":
            rec["status"], rec["error"] = "refusal", str(getattr(msg, "stop_details", None))
        elif msg.stop_reason == "max_tokens":
            rec["status"], rec["error"] = "truncated", "hit max_tokens"
        else:
            try:
                rec["parsed"] = json.loads(text)
            except json.JSONDecodeError as exc:
                rec["status"], rec["error"] = "bad_json", str(exc)
        check = CHECKS.get(job.mode.split("_")[0])  # identification answers have nothing to verify in the text
        if rec["parsed"] is not None and check:
            rec["checks"] = check(rec["parsed"], job.meta)
        return rec

    def _write(self, job: Job, rec: dict) -> None:
        p = self.path(job)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, indent=1, ensure_ascii=False))

    def call(self, job: Job, force: bool = False) -> dict:
        """One synchronous request, with server-side refusal fallback where available."""
        if not force and self.done(job):
            return json.loads(self.path(job).read_text())
        kwargs = self.params(job)
        if self.model in FALLBACK_MODELS:
            raw = self.client.beta.messages.with_raw_response.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs
            )
        else:
            raw = self.client.messages.with_raw_response.create(**kwargs)
        msg = raw.parse()
        rec = self._record(job, msg, request_id=raw.headers.get("request-id"))
        self._write(job, rec)
        return rec

    # ----------------------------------------------------------------- batches
    def submit(self, jobs: list[Job]) -> str | None:
        todo = [j for j in jobs if not self.done(j)]
        if not todo:
            print("Nothing to submit: every job already has a valid record.")
            return None
        keys = [j.key for j in todo]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate job keys in one batch")
        batch = self.client.messages.batches.create(
            requests=[{"custom_id": j.key, "params": self.params(j)} for j in todo]
        )
        manifest = {
            "batch_id": batch.id,
            "model": self.model,
            "effort": self.effort,
            "run_tag": self.run_tag,
            "rubric_version": rubric.RUBRIC_VERSION,
            "created_at": batch.created_at.isoformat(),
            "jobs": {j.key: {"mode": j.mode, "input_sha256": j.input_sha} for j in todo},
        }
        path = LLM_DIR / "batches" / f"{batch.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=1))
        print(f"Submitted {len(todo)} requests as {batch.id}")
        return batch.id

    def collect(self, batch_id: str, jobs: list[Job], wait: bool = False) -> dict:
        """Write records for a finished batch; re-run refusals synchronously with fallback."""
        manifest = json.loads((LLM_DIR / "batches" / f"{batch_id}.json").read_text())
        by_key = {j.key: j for j in jobs}
        while True:
            batch = self.client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended" or not wait:
                break
            time.sleep(60)
        if batch.processing_status != "ended":
            print(f"{batch_id}: {batch.processing_status}, {batch.request_counts}")
            return {"status": batch.processing_status}
        summary = {"ok": 0, "refusal_rerun": 0, "failed": []}
        for result in self.client.messages.batches.results(batch_id):
            job = by_key.get(result.custom_id)
            if job is None or job.input_sha != manifest["jobs"][result.custom_id]["input_sha256"]:
                summary["failed"].append((result.custom_id, "input changed since submission"))
                continue
            if result.result.type != "succeeded":
                summary["failed"].append((result.custom_id, result.result.type))
                continue
            rec = self._record(job, result.result.message, batch_id=batch_id)
            if rec["status"] == "refusal" and self.model in FALLBACK_MODELS:
                rec = self.call(job, force=True)
                summary["refusal_rerun"] += 1
            else:
                self._write(job, rec)
            if rec["status"] == "ok":
                summary["ok"] += 1
            else:
                summary["failed"].append((result.custom_id, rec["status"]))
        return summary

    # ---------------------------------------------------------------- tokens
    def count(self, job: Job) -> int:
        p = self.params(job)
        return self.client.messages.count_tokens(
            model=self.model, system=p["system"], messages=p["messages"]
        ).input_tokens


# --------------------------------------------------------------------- checks
def _check_level(parsed: dict, meta: dict) -> dict:
    text = meta.get("text") or (INTERIM / "texts" / f"{meta['doc_id']}.txt").read_text()
    if meta.get("transform") == "anonymized":
        from ..audit import anonymize

        text = anonymize(text)
    out = {"evidence": verify_quotes([e["quote"] for e in parsed.get("evidence", [])], text)}
    s, c = parsed.get("stance_score"), parsed.get("confidence")
    out["stance_score_in_range"] = s is not None and -1 <= s <= 1
    out["confidence_in_range"] = c is not None and 0 <= c <= 1
    return out


def _check_shift(parsed: dict, meta: dict) -> dict:
    prev = (INTERIM / "texts" / f"{meta['previous_doc_id']}.txt").read_text()
    cur = (INTERIM / "texts" / f"{meta['doc_id']}.txt").read_text()
    changes = parsed.get("changes", [])
    return {
        "before": verify_quotes([c["before"] for c in changes], prev),
        "after": verify_quotes([c["after"] for c in changes], cur),
    }


def _check_sentences(parsed: dict, meta: dict) -> dict:
    got = sorted(x["id"] for x in parsed.get("labels", []))
    return {"complete": got == sorted(meta["ids"])}


CHECKS = {"level": _check_level, "live": _check_level, "shift": _check_shift, "sentences": _check_sentences}


# ------------------------------------------------------------------ job lists
def texts_for(docs: pd.DataFrame) -> dict[str, str]:
    return {d: (INTERIM / "texts" / f"{d}.txt").read_text() for d in docs["doc_id"]}


def level_jobs(docs: pd.DataFrame, anonymized: bool = False) -> list[Job]:
    """One rubric job per document; `anonymized` masks dates, names and rate levels (audit)."""
    jobs = []
    for d in docs.itertuples():
        text = (INTERIM / "texts" / f"{d.doc_id}.txt").read_text()
        meta = {"doc_id": d.doc_id, "doc_type": d.doc_type}
        if anonymized:
            from ..audit import anonymize

            text, meta["transform"] = anonymize(text), "anonymized"
        meta["text_sha256"] = sha(text)
        jobs.append(
            Job(
                "level_anon" if anonymized else "level",
                d.doc_id,
                rubric.LEVEL_SYSTEM,
                rubric.level_message(d.doc_type, text),
                rubric.LEVEL_SCHEMA,
                meta,
            )
        )
    return jobs


def shift_jobs(docs: pd.DataFrame, doc_types=("statement",), decisions: set[str] | None = None) -> list[Job]:
    """Each document read against the previous one of its type. Given the policy decisions, statements are paired
    decision with decision; notices (swap lines, framework reviews) are left out."""
    jobs = []
    for doc_type in doc_types:
        seq = docs[docs.doc_type == doc_type].sort_values(["release_date", "doc_id"])
        if doc_type == "statement" and decisions is not None:
            seq = seq[seq["doc_id"].isin(decisions)]
        for prev, cur in zip(seq.itertuples(), seq.iloc[1:].itertuples()):
            p_text = (INTERIM / "texts" / f"{prev.doc_id}.txt").read_text()
            c_text = (INTERIM / "texts" / f"{cur.doc_id}.txt").read_text()
            jobs.append(
                Job(
                    "shift",
                    cur.doc_id,
                    rubric.SHIFT_SYSTEM,
                    rubric.shift_message(doc_type, p_text, c_text),
                    rubric.SHIFT_SCHEMA,
                    {"doc_id": cur.doc_id, "previous_doc_id": prev.doc_id, "doc_type": doc_type},
                )
            )
    return jobs


def sentence_jobs(sentences: list[str], prefix: str, chunk: int = 25, ids: list[int] | None = None) -> list[Job]:
    """Sentences in chunks; each is labeled under its id (its position, unless `ids` are given)."""
    ids = list(range(len(sentences))) if ids is None else [int(i) for i in ids]
    jobs = []
    for start in range(0, len(sentences), chunk):
        items = list(zip(ids[start : start + chunk], sentences[start : start + chunk]))
        jobs.append(
            Job(
                "sentences",
                f"{prefix}_{start:05d}",
                rubric.SENTENCE_SYSTEM,
                rubric.sentence_message(items),
                rubric.SENTENCE_SCHEMA,
                {"ids": [i for i, _ in items]},
            )
        )
    return jobs


# ---------------------------------------------------------------- aggregation
def load_records(model: str, mode: str) -> list[dict]:
    root = LLM_DIR / model / rubric.RUBRIC_VERSION / mode
    return [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))] if root.exists() else []


def level_scores(model: str, mode: str = "level") -> pd.DataFrame:
    rows = []
    for r in load_records(model, mode):
        if r["status"] != "ok":
            continue
        p = r["parsed"]
        rows.append(
            {
                "doc_id": r["key"],
                "score": max(-1.0, min(1.0, p["stance_score"])),
                "overall_stance": p["overall_stance"],
                "confidence": p["confidence"],
                "policy_relevance": p["policy_relevance"],
                **{d: p[d] for d in rubric.DIMENSIONS},
                "evidence_share": r["checks"]["evidence"]["share"],
                "model_served": r["model_served"],
            }
        )
    return pd.DataFrame(rows)


def live_job(text: str, doc_type: str) -> Job:
    """A one-off scoring job for text pasted into the dashboard."""
    return Job(
        "live",
        f"live_{sha(doc_type + text)[:16]}",
        rubric.LEVEL_SYSTEM,
        rubric.level_message(doc_type, text),
        rubric.LEVEL_SCHEMA,
        {"doc_id": None, "doc_type": doc_type, "text": text, "text_sha256": sha(text)},
    )


def shift_scores(model: str) -> pd.DataFrame:
    rows = [
        {
            "doc_id": r["key"],
            "shift_score": r["parsed"]["shift_score"],
            "before_share": r["checks"]["before"]["share"],
            "after_share": r["checks"]["after"]["share"],
        }
        for r in load_records(model, "shift")
        if r["status"] == "ok"
    ]
    return pd.DataFrame(rows)


def usage_summary(model: str) -> pd.DataFrame:
    prices = settings()["llm"]["prices_per_mtok"].get(model, {"input": float("nan"), "output": float("nan")})
    disc = settings()["llm"]["batch_discount"]
    rows = []
    root = LLM_DIR / model / rubric.RUBRIC_VERSION
    for p in root.glob("*/*.json") if root.exists() else []:
        r = json.loads(p.read_text())
        u = r["usage"]
        mult = disc if r.get("batch_id") else 1.0
        inp = (
            u.get("input_tokens", 0)
            + 1.25 * (u.get("cache_creation_input_tokens") or 0)
            + 0.1 * (u.get("cache_read_input_tokens") or 0)
        )
        cost = mult * (inp * prices["input"] + u.get("output_tokens", 0) * prices["output"]) / 1e6
        rows.append(
            {
                "mode": r["mode"],
                "batch": bool(r.get("batch_id")),
                "status": r["status"],
                "input_tokens": u.get("input_tokens", 0),
                "output_tokens": u.get("output_tokens", 0),
                "cost_usd": cost,
                "created_at": r.get("created_at") or "",
            }
        )
    return pd.DataFrame(
        rows, columns=["mode", "batch", "status", "input_tokens", "output_tokens", "cost_usd", "created_at"]
    )


def month_spend(model: str, today: str | None = None) -> float:
    """What this calendar month's direct calls (UTC) cost at list prices: the yardstick for the scheduled scoring's
    monthly cap. Message Batches are left out: a backfill is started by hand, with its own estimate first."""
    from datetime import UTC, datetime

    month = (today or datetime.now(UTC).date().isoformat())[:7]
    u = usage_summary(model)
    if not len(u):
        return 0.0
    return float(u.loc[u["created_at"].str.startswith(month) & ~u["batch"], "cost_usd"].sum())
