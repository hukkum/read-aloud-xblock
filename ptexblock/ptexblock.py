"""
PTE Read Aloud XBlock (single-question version).

- Records audio in the browser (MediaRecorder via JS)
- Sends base64 audio + reference text to an external scoring API
- Stores last raw pron score (0–90) + feedback JSON in user state
- Exposes a simple numeric score that can be mapped to course grading
"""

from xblock.core import XBlock
from xblock.fields import Scope, String, Float
from xblockutils.studio_editable import StudioEditableXBlockMixin
from web_fragments.fragment import Fragment

import json
import requests
import pkg_resources


# ---------------------------------------------------------------------------
# Resource loader (pkg_resources, relative to this module)
# ---------------------------------------------------------------------------

def _resource_string(path: str) -> str:
    """
    Load a text resource from this XBlock package.

    Path is relative to the *module* package, so:
      "static/html/ptexblock.html"
      "static/css/ptexblock.css"
      "static/js/src/ptexblock.js"
    are all under ptexblock/ptexblock/.
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
      - self.display_name (aka self.title)
      - self.instructions
      - self.reference_text
      - self.student_score
    """

    icon_class = "problem"     # Shows as a "problem" in Studio
    has_score = True   
    # ✨ This is the crucial line for Studio:
    has_author_view = True        

    # Tell StudioEditableXBlockMixin which fields to expose in the Settings form
    editable_fields = (
        "display_name",
        "instructions",
        "reference_text",
        "api_url",
    )

    # ----- Instructor / author settings (Studio "Settings" form) -------------

    display_name = String(
        display_name="Component title",
        default="PTE Read Aloud Practice v0.8",
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

    # ----- Views --------------------------------------------------------------

    def student_view(self, context=None):
        """
        Learner-facing view (also used as author_view in Studio):
        shows title, instructions, reference text, recorder buttons,
        and last saved score + feedback.
        """
        html = _resource_string("static/html/ptexblock.html").format(self=self)
        frag = Fragment(html)
        frag.add_css(_resource_string("static/css/ptexblock.css"))
        frag.add_javascript(_resource_string("static/js/src/ptexblock.js"))
        frag.initialize_js('PTEXBlock')
        return frag

    def author_view(self, context=None):
        """
        Studio preview mode. Keep it identical to student_view so
        you see exactly what learners see instead of a grey box.
        """
        return self.student_view(context)

    def studio_view(self, context=None):
        """
        Studio "Edit" modal.

        We keep this *very* simple on purpose:
        - No external HTML/JS resources that could 500.
        - All real editing is done via the Settings gear (using
          StudioEditableXBlockMixin and editable_fields).
        """
        html = u"""
        <div class="ptex-studio-wrapper">
          <h3>PTE Read Aloud – Studio</h3>
          <p>
            This component is configured from the <strong>Settings</strong>
            dialog in Studio.
          </p>
          <ul>
            <li><strong>Component title</strong> – block title</li>
            <li><strong>Instructions</strong> – text shown above the prompt</li>
            <li><strong>Reference text</strong> – sentence/paragraph to read</li>
            <li><strong>Scoring API URL</strong> – backend endpoint</li>
          </ul>
          <p>No additional options are available in this editor.</p>
        </div>
        """
        return Fragment(html)

    # ----- JSON handler: called from JS after recording ----------------------

    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Receive base64 audio from the browser, call the external scoring API,
        and persist last score + feedback.

        Supports two backend response shapes:
        1) Flat PTE-style metrics (what you have now):
           {
               "accuracy": ...,
               "completeness": ...,
               "fluency": ...,
               "pron_score": ...,
               "prosody": ...,
               "words": [...]
           }

        2) Old style:
           {
               "status": "ok",
               "score": ...,
               "feedback": {
                   "accuracy": ...,
                   ...
               }
           }
        """
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            return {"status": "error", "message": "No audio data received."}

        payload = {
            # For “recorder-only” mode you can leave reference_text blank;
            # backend can just ignore it.
            "reference_text": self.reference_text or "",
            "audio_base64": audio_base64,
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
            # Backend did not return JSON
            return {
                "status": "error",
                "message": f"API returned non-JSON (HTTP {status_code})",
                "raw": resp.text[:2000],
            }

        # Debug on backend
        print("PTEXBlock backend result:", result)

        if not isinstance(result, dict):
            return {"status": "error", "message": "API returned unexpected format."}

        feedback = {}
        pron_score = 0.0

        # --- Case A: flat metrics --------------------------------------------
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

        # --- Case B: older shape with status/score/feedback ------------------
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
        """
        Scenarios visible in the xblock-sdk workbench.
        """
        return [
            (
                "PTE Read Aloud - Single",
                "<ptexblock/>",
            ),
            (
                "PTE Read Aloud - Vertical demo",
                """
                <vertical_demo>
                    <ptexblock/>
                    <ptexblock/>
                </vertical_demo>
                """,
            ),
        ]


# Backwards-compat alias: Workbench / Tutor may still be importing this.
class PTEXBlockWithMixins(PTEXBlock):
    """Alias so existing registrations using PTEXBlockWithMixins keep working."""
    pass
