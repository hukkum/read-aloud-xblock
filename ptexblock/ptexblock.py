"""
PTE Read Aloud XBlock (single-question version).

- Records audio in the browser (MediaRecorder via JS)
- Sends base64 audio + reference text to an external scoring API
- Stores last raw pron score (0–90) + feedback JSON in user state
- Exposes a simple numeric score that can be mapped to course grading
"""

from xblock.core import XBlock
from xblock.fields import Scope, String, Float, Integer  # NEW: Integer
from xblock.fragment import Fragment
from xblockutils.studio_editable import StudioEditableXBlockMixin

import json
import requests
import pkg_resources


# ---------------------------------------------------------------------------
# Resource loader
# ---------------------------------------------------------------------------

def _resource_string(path: str) -> str:
    """
    Load a text resource from this XBlock package.

    Path is relative to the *module* package, so:
      "static/html/ptexblock.html"
      "static/css/ptexblock.css"
      "static/js/src/ptexblock.js"
    """
    data = pkg_resources.resource_string(__name__, path)
    return data.decode("utf-8")


# ---------------------------------------------------------------------------
# Main XBlock
# ---------------------------------------------------------------------------

class PTEXBlock(StudioEditableXBlockMixin, XBlock):
    """
    Single PTE Read-Aloud style question.

    The template (ptexblock.html) expects these attributes:
      - self.display_name or self.title
      - self.instructions
      - self.reference_text
      - self.student_score

    And for the upgraded UI:
      - self.mode               (practice | exam)
      - self.question_type      (e.g., read_aloud)
      - self.preroll_delay      (seconds)
      - self.recording_limit    (seconds)
      - self.max_attempts       (practice only)
    """

    icon_class = "problem"     # Shows as a "problem" in Studio
    has_score = True           # LMS knows this block can produce a score

    # Tell Studio that we have an author_view it should call in preview.
    has_author_view = True

    # Fields that Studio should make editable in the (legacy) editor.
    editable_fields = (
        "display_name",
        "instructions",
        "reference_text",
        "api_url",
        "weight",
        # NEW: mode + timing config
        "mode",
        "question_type",
        "preroll_delay",
        "recording_limit",
        "max_attempts",
    )

    # ----- Instructor / author settings (Studio "Settings" form) -------------

    display_name = String(
        display_name="Component title",
        default="PTE Read Aloud Practice",
        scope=Scope.settings,
        help="Title shown to learners and in Studio.",
    )

    instructions = String(
        display_name="Instructions",
        default=(
            "Look at the text below. In 40 seconds, you must read this text "
            "aloud as naturally and clearly as possible. The microphone will "
            "stop after 3 seconds of silence!"
        ),
        scope=Scope.content,
        help="High-level instructions shown to learners.",
    )

    reference_text = String(
        display_name="Reference text",
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="Text the learner should read aloud.",
    )

    api_url = String(
        display_name="Scoring API URL",
        default="https://api.abroadprocess.com/api/pte/read-aloud",
        scope=Scope.settings,
        help="HTTP endpoint that accepts audio + reference text and returns scores.",
    )

    weight = Float(
        display_name="Problem weight",
        default=1.0,
        scope=Scope.settings,
        help="Maximum score this question contributes to the course grade.",
    )

    # NEW: mode & timing configuration ---------------------------------------

    mode = String(
        display_name="Mode (practice or exam)",
        default="practice",   # default keeps current behavior
        scope=Scope.settings,
        help=(
            "Use 'practice' to show AI feedback and allow multiple attempts, "
            "or 'exam' to hide feedback and allow only one submission."
        ),
    )

    question_type = String(
        display_name="Question type label",
        default="read_aloud",
        scope=Scope.settings,
        help="Label sent to the backend (optional) to identify this question type.",
    )

    preroll_delay = Integer(
        display_name="Prep time (seconds)",
        default=3,
        scope=Scope.settings,
        help="Countdown before recording starts.",
    )

    recording_limit = Integer(
        display_name="Speaking time limit (seconds)",
        default=40,
        scope=Scope.settings,
        help="Maximum length of the recording.",
    )

    max_attempts = Integer(
        display_name="Max attempts (practice mode)",
        default=3,
        scope=Scope.settings,
        help="Maximum number of attempts in practice mode (ignored in exam mode).",
    )

    # ----- Per-student state --------------------------------------------------

    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last raw pronunciation score (0–90) returned by the API.",
    )

    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="JSON feedback blob returned by the API.",
    )

    student_words = String(
        default="[]",
        scope=Scope.user_state,
        help="Word-level details as a JSON list.",
    )

    # ----- Compatibility helpers ---------------------------------------------

    @property
    def title(self):
        """
        Alias for templates that use {self.title}.
        """
        return self.display_name

    @property
    def is_practice(self) -> bool:
        return (self.mode or "").lower() == "practice"

    @property
    def is_exam(self) -> bool:
        return (self.mode or "").lower() == "exam"

    # ----- Views --------------------------------------------------------------

    def student_view(self, context=None):
        """
        Learner-facing view (and also Studio preview): shows recorder,
        status/progress, and (in practice mode) feedback.
        """
        badge_label = "Exam Question" if self.is_exam else "Practice Mode"

        html = _resource_string("static/html/ptexblock.html").format(
            self=self,
            badge_label=badge_label,
        )
        frag = Fragment(html)
        frag.add_css(_resource_string("static/css/ptexblock.css"))
        frag.add_javascript(_resource_string("static/js/src/ptexblock.js"))

        # JS config: pass everything explicitly so we don't depend on data-attrs
        js_config = {
            "mode": (self.mode or "practice"),
            "question_type": (self.question_type or "read_aloud"),
            "preroll_delay": int(self.preroll_delay or 0),
            "recording_limit": int(self.recording_limit or 40),
            "max_attempts": int(self.max_attempts or (1 if self.is_exam else 3)),
        }

        frag.initialize_js('PTEXBlock', js_config)
        return frag



    def author_view(self, context=None):
        """
        Studio preview view. We just reuse the student_view so authors see
        exactly what learners see.
        """
        return self.student_view(context)

    # NOTE: no custom studio_view or studio_submit here.
    # StudioEditableXBlockMixin provides those and wires up the generic
    # field editor UI, similar to the Google Calendar XBlock.

    # ----- JSON handler: called from JS after recording ----------------------

    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Receive base64 audio from the browser, call the external scoring API,
        and persist last score + feedback.
        """
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            return {"status": "error", "message": "No audio data received."}

        payload = {
            "reference_text": self.reference_text or "",
            "audio_base64": audio_base64,
            # NOTE: if/when your backend is ready, you can safely add:
            # "mode": self.mode,
            # "question_type": self.question_type,
        }

        # --- Call external API ------------------------------------------------
        try:
            resp = requests.post(self.api_url, json=payload, timeout=20)
            status_code = resp.status_code
            resp.raise_for_status()
        except Exception as exc:
            return {"status": "error", "message": f"API error: {exc!s}"}

        try:
            result = resp.json()
        except ValueError:
            return {
                "status": "error",
                "message": f"API returned non-JSON (HTTP {status_code})",
                "raw": resp.text[:2000],
            }

        print("PTEXBlock backend result:", result)

        if not isinstance(result, dict):
            return {"status": "error", "message": "API returned unexpected format."}

        feedback = {}
        pron_score = 0.0

        # --- Case A: flat PTE-style metrics ----------------------------------
        if any(
            key in result
            for key in ("pron_score", "accuracy", "fluency", "prosody", "completeness", "words")
        ):
            feedback = {
                "pron_score": result.get("pron_score"),
                "accuracy": result.get("accuracy"),
                "fluency": result.get("fluency"),
                "prosody": result.get("prosody"),
                "completeness": result.get("completeness"),
                "words": result.get("words") or [],
            }
            pron_score = feedback.get("pron_score") or 0.0

        # --- Case B: older wrapped shape -------------------------------------
        else:
            api_status = result.get("status")
            if api_status not in (None, "ok"):
                return {
                    "status": "error",
                    "message": (
                        result.get("message")
                        or result.get("error")
                        or "Scoring API returned an error."
                    ),
                }

            inner_fb = result.get("feedback") or {}
            feedback = {
                "pron_score": inner_fb.get("pron_score"),
                "accuracy": inner_fb.get("accuracy"),
                "fluency": inner_fb.get("fluency"),
                "prosody": inner_fb.get("prosody"),
                "completeness": inner_fb.get("completeness"),
                "words": inner_fb.get("words") or result.get("words") or [],
            }
            if "score" in result:
                pron_score = result["score"]
            else:
                pron_score = feedback.get("pron_score") or 0.0

        # --- Persist into student state --------------------------------------
        if isinstance(pron_score, (int, float)):
            self.student_score = float(pron_score)
        else:
            self.student_score = 0.0

        self.student_feedback = json.dumps(feedback)
        self.student_words = json.dumps(feedback.get("words") or [])

        return {
            "status": "ok",
            "score": self.student_score,
            "feedback": feedback,
        }

    # ----- Grading hooks ------------------------------------------------------

    def max_score(self):
        return float(self.weight or 1.0)

    def calculate_score(self):
        """
        Map 0–90 pronunciation score onto 0–weight for LMS gradebook.
        """
        raw = float(self.student_score or 0.0)
        return (raw / 90.0) * self.max_score()

    # ----- Workbench scenarios -----------------------------------------------

    @staticmethod
    def workbench_scenarios():
        return [
            ("PTE Read Aloud - Practice",
            '<ptexblock mode="practice" preroll_delay="5" recording_limit="40" '
            'max_attempts="3" display_name="PTE Practice Recorder"/>'),

            ("PTE Read Aloud - Exam",
            '<ptexblock mode="exam" preroll_delay="10" recording_limit="40" '
            'max_attempts="1" display_name="PTE Exam Recorder"/>'),
        ]



# Backwards-compat alias
class PTEXBlockWithMixins(PTEXBlock):
    """Alias so existing registrations using PTEXBlockWithMixins keep working."""
    pass
