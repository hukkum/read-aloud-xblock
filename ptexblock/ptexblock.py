import json
import requests

from importlib.resources import files

from web_fragments.fragment import Fragment
from xblock.core import XBlock
from xblock.fields import Scope, String, Float, Boolean
from xblock.utils.studio_editable import StudioEditableXBlockMixin


class PTEXBlock(StudioEditableXBlockMixin, XBlock):
    """
    PTE Read Aloud XBlock

    - Student records audio, which is scored by an external API.
    - Instructor can edit title, instructions, reference text, API URL, and weight in Studio.
    """

    # ====== BASIC METADATA / SETTINGS ======

    display_name = String(
        display_name="Component Title",
        default="PTE Read Aloud Practice",
        scope=Scope.settings,
        help="Title shown to learners in the course."
    )

    instructions = String(
        display_name="Instructions Shown to Learner",
        default="Read the following text aloud:",
        scope=Scope.content,
        help="Short instructions displayed above the reference text."
    )

    reference_text = String(
        display_name="Reference Text",
        default="Globalization has significantly changed the modern economy.",
        scope=Scope.content,
        help="The text the learner must read aloud."
    )

    api_url = String(
        display_name="Scoring API URL",
        default="http://127.0.0.1:5001/api/pte/read-aloud",
        scope=Scope.settings,
        help="Backend endpoint that scores the read-aloud audio."
    )

    # Grading / problem behavior
    has_score = Boolean(
        display_name="This problem is graded",
        default=True,
        scope=Scope.settings
    )

    weight = Float(
        display_name="Problem Weight",
        default=1.0,
        scope=Scope.settings,
        help="Weight of this problem in the overall course grade."
    )

    # Make it look/behave like a standard problem in Studio/LMS
    icon_class = "problem"

    # ====== PER-STUDENT STATE ======

    student_score = Float(
        default=0.0,
        scope=Scope.user_state,
        help="Last pronunciation score for this learner."
    )

    student_feedback = String(
        default="",
        scope=Scope.user_state,
        help="Raw JSON feedback from the scoring API."
    )

    student_words = String(
        default="[]",
        scope=Scope.user_state,
        help="Word-level feedback JSON from the scoring API."
    )

    # ====== STUDIO EDITABLE FIELDS ======

    # These fields will appear in the standard Studio “Edit” dialog
    editable_fields = (
        "display_name",
        "instructions",
        "reference_text",
        "api_url",
        "has_score",
        "weight",
    )

    # NOTE: We DO NOT define our own studio_view here.
    # StudioEditableXBlockMixin provides a default editor for editable_fields.

    # ====== STATIC FILE LOADER ======

    def resource(self, path: str) -> str:
        """
        Load a resource file (HTML/JS/CSS) from this XBlock package.
        Example: resource("static/html/ptexblock.html")
        """
        return files(__package__).joinpath(path).read_text(encoding="utf-8")

    # ====== STUDENT VIEW ======

    def student_view(self, context=None):
        """
        What the learner sees in the LMS.
        """
        html = self.resource("static/html/ptexblock.html").format(
            title=self.display_name,
            instructions=self.instructions,
            reference_text=self.reference_text,
            last_score=self.student_score,
        )

        frag = Fragment(html)
        frag.add_css(self.resource("static/css/ptexblock.css"))
        frag.add_javascript(self.resource("static/js/src/ptexblock.js"))
        frag.initialize_js("PTEXBlock")
        return frag

    # ====== STUDENT AJAX HANDLER ======

    @XBlock.json_handler
    def submit_audio(self, data, suffix=""):
        """
        Called by JS when the learner finishes recording.
        Sends base64 audio + reference text to the scoring API, then stores
        the resulting score/feedback for this learner.
        """
        try:
            audio_base64 = data.get("audio_base64")
            if not audio_base64:
                return {"status": "error", "message": "Missing audio data"}

            payload = {
                "reference_text": self.reference_text,
                "audio_base64": audio_base64,
            }

            resp = requests.post(self.api_url, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                return {"status": "error", "message": result.get("error")}

            # Store learner state based on API response
            self.student_score = float(result.get("pron_score", 0.0))
            self.student_feedback = json.dumps(result)
            self.student_words = json.dumps(result.get("words", []))

            return {
                "status": "ok",
                "score": self.student_score,
                "feedback": result,
            }

        except requests.RequestException as e:
            return {"status": "error", "message": f"Network error: {e}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ====== GRADING HOOKS ======

    def max_score(self):
        # Azure + PTE-style scoring is typically 0–90
        return 90.0

    def get_score(self):
        return float(self.student_score)

    def calculate_score(self):
        """
        Called by the LMS to compute the learner's score contribution.
        For now we just pass through the pronunciation score.
        Later we can map 0–90 to a smaller 0–1/0–2 scheme if needed.
        """
        return float(self.student_score)

    # ====== WORKBENCH (for xblock-sdk only) ======

    @staticmethod
    def workbench_scenarios():
        """
        For xblock-sdk workbench testing.
        """
        return [
            ("PTE Read Aloud Inline", "<ptexblock/>"),
        ]
