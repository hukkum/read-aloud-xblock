import json
import requests
from importlib.resources import files

from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import Scope, String, Float


class PTEXBlock(XBlock):
    """
    PTE Read Aloud XBlock: records audio in browser, sends to external API,
    shows detailed feedback, and stores a 0–90 pronunciation score in LMS.
    """

    # Instructor-facing content fields
    title = String(
        default="PTE Read Aloud Practice",
        scope=Scope.content,
        help="Title shown to learners."
    )

    instructions = String(
        default=(
            "Look at the text below. In 40 seconds, you must read this text aloud "
            "as naturally and clearly as possible. You have 40 seconds to read aloud. "
            "The microphone will stop after 3 seconds of silence!"
        ),
        scope=Scope.content,
        help="PTE-style instructions shown above the text."
    )

    reference_text = String(
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="The text learners must read aloud."
    )

    # Settings (in Studio / advanced settings)
    api_url = String(
        default="https://api.abroadprocess.com/api/pte/read-aloud",
        scope=Scope.settings,
        help="External PTE scoring API endpoint."
    )

    # Per-learner stored state
    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last saved pronunciation score (0–90) from the API."
    )
    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="Raw JSON feedback as a string (overall + subscores)."
    )
    student_words = String(
        default="[]",
        scope=Scope.user_state,
        help="Word-level feedback as JSON string."
    )

    # -----------------------
    # Helpers / assets
    # -----------------------
    def resource_string(self, path: str) -> str:
        """
        Load a file from static/ or templates/ inside this package.
        This is the pattern used by the default SDK cookiecutter.
        """
        return files(__package__).joinpath(path).read_text(encoding="utf-8")

    # -----------------------
    # Main learner view
    # -----------------------
    def student_view(self, context=None):
        """
        The primary view shown to learners.
        """
        html = self.resource_string("static/html/ptexblock.html")
        # Inject self.* values into the template
        html = html.format(self=self)

        frag = Fragment(html)
        frag.add_css(self.resource_string("static/css/ptexblock.css"))
        frag.add_javascript(self.resource_string("static/js/src/ptexblock.js"))
        frag.initialize_js("PTEXBlock")
        return frag

    # -----------------------
    # JSON handler: audio → API → feedback
    # -----------------------
    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Receives base64 audio from JS and forwards it to the external PTE API.
        Returns structured feedback the JS can render.
        """
        audio_base64 = data.get("audio_base64")
        if not audio_base64:
            return {"status": "error", "message": "No audio found in request."}

        payload = {
            "reference_text": self.reference_text,
            "audio_base64": audio_base64,
        }

        # Call external Flask API
        try:
            resp = requests.post(self.api_url, json=payload, timeout=30)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Network error while contacting scoring API: {e}",
            }

        try:
            result = resp.json()
        except ValueError:
            return {
                "status": "error",
                "message": f"Invalid JSON from scoring API (HTTP {resp.status_code}).",
            }

        if resp.status_code != 200 or "error" in result:
            return {
                "status": "error",
                "message": result.get(
                    "error",
                    f"Scoring API error (HTTP {resp.status_code}).",
                ),
            }

        # Normalize feedback payload from your Flask API
        feedback = {
            "pron_score": result.get("pron_score"),
            "accuracy": result.get("accuracy"),
            "fluency": result.get("fluency"),
            "prosody": result.get("prosody"),
            "completeness": result.get("completeness"),
            "words": result.get("words", []),
        }

        # Store the pronunciation score as the "grade" for this block.
        # (Later, you can average across items in the course if you want.)
        try:
            self.student_score = float(feedback["pron_score"] or 0.0)
        except (TypeError, ValueError):
            self.student_score = 0.0

        self.student_feedback = json.dumps(feedback)
        self.student_words = json.dumps(feedback["words"])

        return {
            "status": "ok",
            "score": self.student_score,
            "feedback": feedback,
        }

    # -----------------------
    # Gradebook integration
    # -----------------------
    def max_score(self):
        """
        Max PTE-like score is 90.
        The LMS can treat this as "out of 90", or you can later rescale.
        """
        return 90.0

    def calculate_score(self):
        """
        Return the last stored PTE pronunciation score.
        For practice sets, you can ignore it in course grading.
        For mock tests, you can average these at course level.
        """
        return float(self.student_score)

    # -----------------------
    # Workbench scenario
    # -----------------------
    @staticmethod
    def workbench_scenarios():
        """
        Scenario so it appears in the SDK workbench list.
        """
        return [
            (
                "PTE Read Aloud (inline)",
                """
                <vertical_demo>
                    <ptexblock/>
                </vertical_demo>
                """,
            ),
        ]
