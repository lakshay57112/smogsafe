"""Gemini calls: daily plan (structured JSON), what-if chat and local advisories
(both grounded with Google Search, with sources)."""

from __future__ import annotations

import json
import logging
import re

from google import genai
from google.genai import errors, types

from app.schemas import AIPlan

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {
    "en": "simple English",
    "hi": "simple Hindi in Devanagari script",
    "hinglish": "Hinglish (Hindi written in Roman script, mixed with common English words)",
}

PLAN_SYSTEM = """You are SmogSafe, a practical smog-season companion for Indian families.
You get CONTEXT as JSON: live air data for the user's location, their household, and pre-computed
impact numbers for different kinds of actions.

Write today's plan:
- 5 to 7 actions, ordered through the day, specific to the times in best_window and worst_window.
- Prefer cheap, realistic actions for Indian homes: closing windows at peak hours, wet mopping,
  lid-on cooking with the exhaust running, metro/bus/carpool, fitted N95 masks, indoor exercise,
  no incense or coils, composting leaves instead of burning, reporting burning on the CPCB Sameer app.
- For each action set impact_key to the one key in CONTEXT.impacts that measures that exact action,
  or "none". In "why", you may quote that impact's numbers, but never invent new numbers.
- family: one entry per household member (use their member_id), 2-3 short tips each, matched to
  their computed risk level, age and conditions. For health conditions, tell them to follow their
  doctor's action plan and to seek care for warning signs. Never diagnose or prescribe.
- indoor_checklist: 4-6 items for tonight. swaps: exactly 3 sustainable swaps.
- If the air is Good or Satisfactory, say so honestly and keep the plan light.
- Never state an AQI or concentration that is not in CONTEXT.
Write all text in {language}. Keep every string short and friendly, like a caring neighbour."""

ASK_SYSTEM = """You are SmogSafe, a smog-season assistant for Indian families.
Answer the user's question about air pollution, health precautions, low-emission routines,
indoor air or the impact of their choices.

Rules:
- Use the live CONTEXT below for anything about today's air in their area. Do not contradict it.
- Use Google Search for current facts (local advisories, GRAP stages, schemes, product guidance, studies).
- For "what if" questions, estimate the impact using the FACTORS in CONTEXT and show the simple math
  in one line, e.g. "(0.14 − 0.025) kg/km × 20 km × 3 days = 6.9 kg CO₂ a week". Say numbers are rough.
- Keep it practical: max ~170 words, short paragraphs or "- " bullets, **bold** the key numbers.
- Not a doctor: for symptoms such as chest pain, severe breathlessness or bluish lips, tell them to seek
  medical care immediately.
- Reply in {language}.

CONTEXT:
{context}"""

ADVISORY_PROMPT = """What are the latest official air-pollution advisories, restrictions and alerts for
{place}{state}, India, as of {today}? Include the GRAP stage if the city is in Delhi NCR, school or office
advisories, construction or vehicle restrictions, and health advisories. Only include items from the
last 14 days. Reply with 3 to 5 bullet points, each starting with "- ", each under 30 words, starting
with the date if known. If nothing recent is found, reply with one bullet saying so."""


class AIUnavailable(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# Errors that usually mean "Google Search grounding isn't allowed for this key"
# (free-tier keys don't include it on Gemini 3 models) or its quota ran out.
SEARCH_BLOCKED_CODES = {400, 403, 429}
NO_SEARCH_NOTE = (
    "\n\nLive Google Search is not available right now, so answer from your own knowledge and the "
    "CONTEXT. If the question needs very recent news (today's restrictions, GRAP stage), say you "
    "can't check live news and point them to official sources."
)


def add_citations(text: str, supports, web_chunk_numbers: dict[int, int]) -> str:
    """Insert [n] markers after grounded segments. Segment indices are UTF-8 byte offsets."""
    data = text.encode("utf-8")
    inserts: list[tuple[int, str]] = []
    for s in supports or []:
        seg = getattr(s, "segment", None)
        end = getattr(seg, "end_index", None) if seg else None
        if end is None or end > len(data):
            continue
        nums = sorted({web_chunk_numbers[i] for i in (s.grounding_chunk_indices or []) if i in web_chunk_numbers})
        if nums:
            inserts.append((end, "".join(f"[{n}]" for n in nums)))
    for end, marker in sorted(inserts, key=lambda x: x[0], reverse=True):
        data = data[:end] + marker.encode() + data[end:]
    return data.decode("utf-8", errors="ignore")


def extract_grounded(resp) -> dict:
    """Pull answer text, numbered sources, search queries and the Search Suggestions widget."""
    text = (getattr(resp, "text", None) or "").strip()
    out = {"answer": text, "sources": [], "search_queries": [], "suggestions_html": ""}
    candidates = getattr(resp, "candidates", None) or []
    gm = getattr(candidates[0], "grounding_metadata", None) if candidates else None
    if not gm:
        return out

    numbers: dict[int, int] = {}
    seen: dict[str, int] = {}
    for i, chunk in enumerate(gm.grounding_chunks or []):
        web = getattr(chunk, "web", None)
        if not web or not web.uri:
            continue
        if web.uri in seen:
            numbers[i] = seen[web.uri]
            continue
        n = len(out["sources"]) + 1
        seen[web.uri] = n
        numbers[i] = n
        out["sources"].append({"n": n, "title": web.title or web.domain or "Source", "uri": web.uri})

    if text and gm.grounding_supports:
        try:
            out["answer"] = add_citations(text, gm.grounding_supports, numbers)
        except Exception:  # citations are a nice-to-have; never break the answer
            log.exception("Could not add citations")
    out["search_queries"] = list(gm.web_search_queries or [])
    if gm.search_entry_point and gm.search_entry_point.rendered_content:
        out["suggestions_html"] = gm.search_entry_point.rendered_content
    return out


def parse_bullets(text: str) -> list[str]:
    items = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)", line)
        if m and m.group(1).strip():
            items.append(m.group(1).strip())
    if not items and text.strip():
        items = [text.strip()]
    return items[:6]


class GeminiService:
    def __init__(self, api_key: str, model: str, fallback_model: str):
        self.model = model
        self.fallback_model = fallback_model
        self._client = (
            genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000)) if api_key else None
        )

    @property
    def available(self) -> bool:
        return self._client is not None

    async def _generate(self, contents, config: types.GenerateContentConfig):
        if not self._client:
            raise AIUnavailable("No GEMINI_API_KEY configured")
        last_exc: Exception | None = None
        for model in dict.fromkeys([self.model, self.fallback_model]):
            try:
                return await self._client.aio.models.generate_content(model=model, contents=contents, config=config)
            except errors.ClientError as exc:
                log.warning("Gemini error %s on %s: %s", exc.code, model, getattr(exc, "message", exc))
                # 404/400 can mean this model name isn't available for the key; try the fallback model.
                if exc.code in (400, 404):
                    last_exc = exc
                    continue
                raise AIUnavailable(f"Gemini error {exc.code}", exc.code) from exc
            except errors.APIError as exc:
                log.warning("Gemini error %s on %s: %s", exc.code, model, getattr(exc, "message", exc))
                raise AIUnavailable(f"Gemini error {exc.code}", exc.code) from exc
        raise AIUnavailable("Gemini request failed", getattr(last_exc, "code", None)) from last_exc

    async def daily_plan(self, context: dict, language: str) -> AIPlan:
        config = types.GenerateContentConfig(
            system_instruction=PLAN_SYSTEM.format(language=LANGUAGE_NAMES[language]),
            response_mime_type="application/json",
            response_schema=AIPlan,
            temperature=0.5,
        )
        resp = await self._generate(json.dumps(context, ensure_ascii=False), config)
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, AIPlan):
            return parsed
        if parsed:
            return AIPlan.model_validate(parsed)
        return AIPlan.model_validate_json(resp.text or "{}")

    async def ask(self, question: str, context: dict, history: list[dict], language: str) -> dict:
        contents = [types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])]) for turn in history]
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        system = ASK_SYSTEM.format(language=LANGUAGE_NAMES[language], context=json.dumps(context, ensure_ascii=False))
        grounded_config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.4,
        )
        try:
            resp = await self._generate(contents, grounded_config)
            return {**extract_grounded(resp), "grounded": True}
        except AIUnavailable as exc:
            if exc.code not in SEARCH_BLOCKED_CODES:
                raise
            log.warning("Google Search grounding failed (%s); answering without live search", exc.code)
        plain_config = types.GenerateContentConfig(system_instruction=system + NO_SEARCH_NOTE, temperature=0.4)
        resp = await self._generate(contents, plain_config)
        return {**extract_grounded(resp), "grounded": False}

    async def advisories(self, place: str, state: str, today: str) -> dict:
        prompt = ADVISORY_PROMPT.format(place=place, state=f", {state}" if state else "", today=today)
        config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0.2)
        resp = await self._generate(prompt, config)
        grounded = extract_grounded(resp)
        # Bullets are shown without inline markers; sources are listed underneath.
        plain = (getattr(resp, "text", None) or "").strip()
        return {
            "items": parse_bullets(plain),
            "sources": grounded["sources"],
            "suggestions_html": grounded["suggestions_html"],
        }
